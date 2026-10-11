"""단일 종목 봉 기반 백테스트 엔진 (PRD FR-03).

체결 가정:
- t봉 마감 신호 → t+1봉 시가에 체결 (신호 봉 종가 소급 체결 금지)
- 진입·지표 청산은 시가 ± 슬리피지, 수수료는 테이커 기준 양방향
- 손절·익절은 진입 체결가와 신호 봉 ATR로 고정. 같은 봉에서 둘 다 닿으면 손절 우선(보수적)
- 시가가 손절선을 넘어 갭이 나면 시가에 손절 체결
- 펀딩: funding_rate 열이 있으면 해당 봉 시각에 포지션 명목가치 × 요율을 반영 (롱 지불 / 숏 수취)
- 수량: 리스크 설정(주문별 계획 손실, 종목 익스포저, 레버리지) 중 가장 엄격한 값, 아래로 반올림
"""

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.core.risk import RiskSettings
from app.strategies.base import Strategy


class CostModel(BaseModel):
    taker_fee_bps: float = Field(5.0, ge=0, description="테이커 수수료 (bp)")
    slippage_bps: float = Field(2.0, ge=0, description="진입·청산 슬리피지 (bp)")
    qty_step: float = Field(0.0, ge=0, description="수량 단위 (0이면 반올림 안 함)")
    min_notional: float = Field(5.0, ge=0, description="최소 주문금액 (USDT)")


@dataclass
class Trade:
    side: str
    entry_time: str
    entry_price: float
    qty: float
    stop: float
    take_profit: float
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    fees: float = 0.0
    funding: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    bars_held: int = 0
    ambiguous_bar: bool = False


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    skipped_signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _plain(
            {
                "trades": [asdict(t) for t in self.trades],
                "equity_curve": self.equity_curve,
                "metrics": self.metrics,
                "skipped_signals": self.skipped_signals,
            }
        )


def _plain(obj):
    """numpy 스칼라를 JSON 직렬화 가능한 파이썬 타입으로 변환."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _round_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step + 1e-12) * step


def size_position(
    equity: float, entry: float, stop: float, risk: RiskSettings, cost: CostModel
) -> tuple[float, str]:
    """리스크 한도 중 가장 엄격한 조건으로 수량 계산. (qty, 거부 사유)"""
    e_bot = equity * risk.capital_usage_pct / 100
    # 손절 시 비용 완충분: 진입·청산 수수료 + 청산 슬리피지
    per_unit_loss = abs(entry - stop) + entry * (2 * cost.taker_fee_bps + cost.slippage_bps) / 1e4
    if per_unit_loss <= 0:
        return 0.0, "invalid_stop"
    qty_by_risk = e_bot * risk.risk_per_trade_pct / 100 / per_unit_loss
    qty_by_exposure = e_bot * min(risk.symbol_exposure_x, risk.gross_exposure_x) / entry
    qty_by_leverage = e_bot * risk.leverage * (1 - risk.min_free_margin_pct / 100) / entry
    qty = _round_down(min(qty_by_risk, qty_by_exposure, qty_by_leverage), cost.qty_step)
    if qty <= 0 or qty * entry < cost.min_notional:
        # 최소 주문을 맞추려고 위험 예산을 넘겨 올림하지 않는다 (PRD FR-08, FR-19)
        return 0.0, "below_min_notional"
    return qty, ""


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    risk: RiskSettings,
    cost: CostModel,
    initial_equity: float = 500.0,
    apply_loss_limits: bool = True,
) -> BacktestResult:
    data = strategy.compute(df).reset_index(drop=True)
    p = strategy.params
    fee = cost.taker_fee_bps / 1e4
    slip = cost.slippage_bps / 1e4
    has_funding = "funding_rate" in data.columns

    result = BacktestResult()
    skipped: dict[str, int] = {}
    cash = initial_equity  # 실현 손익 반영 자산
    pos: Trade | None = None
    pending: str | None = None  # 다음 봉 시가에 실행할 동작: "long" / "short" / "exit:<reason>"
    pending_atr = 0.0
    cooldown_until = -1
    entry_idx = 0
    peak = initial_equity
    daily_start_equity = initial_equity
    current_day = None
    locked_until_day = None
    dd_locked = False

    def close_pos(i: int, price: float, reason: str, ambiguous: bool = False):
        nonlocal cash, pos, cooldown_until
        assert pos is not None
        sign = 1 if pos.side == "long" else -1
        exit_fee = price * pos.qty * fee
        pos.exit_time = str(data.at[i, "open_time"])
        pos.exit_price = price
        pos.exit_reason = reason
        pos.gross_pnl = sign * (price - pos.entry_price) * pos.qty
        pos.fees += exit_fee
        pos.net_pnl = pos.gross_pnl - pos.fees + pos.funding
        pos.bars_held = i - entry_idx
        pos.ambiguous_bar = pos.ambiguous_bar or ambiguous
        cash += pos.gross_pnl - exit_fee
        result.trades.append(pos)
        pos = None
        cooldown_until = i + p.cooldown_bars

    for i in range(len(data)):
        row = data.iloc[i]
        o, h, lo, c = row["open"], row["high"], row["low"], row["close"]
        ts = pd.Timestamp(row["open_time"])
        day = ts.date()
        if day != current_day:
            current_day = day
            mark = cash + (
                0
                if pos is None
                else (1 if pos.side == "long" else -1) * (o - pos.entry_price) * pos.qty
            )
            daily_start_equity = mark

        # 1) 시가에 대기 동작 실행
        if pending is not None:
            if pending.startswith("exit") and pos is not None:
                px = o * (1 - slip) if pos.side == "long" else o * (1 + slip)
                close_pos(i, px, pending.split(":", 1)[1])
            elif pending in ("long", "short") and pos is None:
                px = o * (1 + slip) if pending == "long" else o * (1 - slip)
                dist = p.stop_atr_multiple * pending_atr
                tp_dist = p.take_profit_atr_multiple * pending_atr
                stop = px - dist if pending == "long" else px + dist
                tp = px + tp_dist if pending == "long" else px - tp_dist
                qty, why = size_position(cash, px, stop, risk, cost)
                if qty > 0:
                    pos = Trade(
                        pending, str(row["open_time"]), px, qty, stop, tp, fees=px * qty * fee
                    )
                    cash -= px * qty * fee
                    entry_idx = i
                else:
                    skipped[why] = skipped.get(why, 0) + 1
            pending = None

        # 2) 펀딩 반영
        if pos is not None and has_funding and not np.isnan(row["funding_rate"]):
            sign = 1 if pos.side == "long" else -1
            amt = -sign * pos.qty * o * row["funding_rate"]
            pos.funding += amt
            cash += amt

        # 3) 봉 내부 손절·익절
        if pos is not None:
            if pos.side == "long":
                hit_sl, hit_tp = lo <= pos.stop, h >= pos.take_profit
                if o <= pos.stop:
                    close_pos(i, o * (1 - slip), "stop_gap")
                elif hit_sl:
                    close_pos(i, pos.stop * (1 - slip), "stop", ambiguous=hit_tp)
                elif hit_tp:
                    close_pos(i, pos.take_profit, "take_profit")
            else:
                hit_sl, hit_tp = h >= pos.stop, lo <= pos.take_profit
                if o >= pos.stop:
                    close_pos(i, o * (1 + slip), "stop_gap")
                elif hit_sl:
                    close_pos(i, pos.stop * (1 + slip), "stop", ambiguous=hit_tp)
                elif hit_tp:
                    close_pos(i, pos.take_profit, "take_profit")

        # 4) 봉 마감 평가자산·손실 한도 (PRD FR-09)
        unreal = 0.0
        if pos is not None:
            unreal = (1 if pos.side == "long" else -1) * (c - pos.entry_price) * pos.qty
        equity = cash + unreal
        peak = max(peak, equity)
        e_bot_peak = peak * risk.capital_usage_pct / 100
        e_bot_day = daily_start_equity * risk.capital_usage_pct / 100
        if peak - equity >= e_bot_peak * risk.max_drawdown_pct / 100:
            dd_locked = True
        if daily_start_equity - equity >= e_bot_day * risk.daily_loss_pct / 100:
            locked_until_day = day
        locked = apply_loss_limits and (dd_locked or locked_until_day == day)
        result.equity_curve.append(
            {"time": str(row["open_time"]), "equity": round(equity, 6), "locked": locked}
        )

        # 5) 다음 봉 동작 결정
        if pos is not None:
            if locked:
                pending = "exit:risk_lock"
            elif (
                pos.side == "long" and row["exit_long"] or pos.side == "short" and row["exit_short"]
            ):
                pending = "exit:signal"
            elif i + 1 - entry_idx >= p.max_holding_bars:
                pending = "exit:max_holding"
        elif not locked and i >= cooldown_until:
            if row["entry_long"]:
                pending, pending_atr = "long", row["atr"]
            elif row["entry_short"]:
                pending, pending_atr = "short", row["atr"]
        elif locked and (row["entry_long"] or row["entry_short"]):
            skipped["risk_locked"] = skipped.get("risk_locked", 0) + 1

    if pos is not None:
        last = len(data) - 1
        close_pos(last, data.at[last, "close"], "end_of_data")
        result.equity_curve[-1]["equity"] = round(cash, 6)

    result.skipped_signals = skipped
    result.metrics = _plain(compute_metrics(result, initial_equity))
    return result


def compute_metrics(result: BacktestResult, initial_equity: float) -> dict:
    trades = result.trades
    eq = pd.Series([e["equity"] for e in result.equity_curve], dtype=float)
    final = float(eq.iloc[-1]) if len(eq) else initial_equity
    dd = float(((eq.cummax() - eq) / eq.cummax()).max()) if len(eq) else 0.0
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl <= 0]
    rets = eq.pct_change().dropna()
    sharpe = (
        float(rets.mean() / rets.std() * math.sqrt(24 * 365))
        if len(rets) > 1 and rets.std() > 0
        else 0.0
    )
    return {
        "initial_equity": initial_equity,
        "final_equity": round(final, 4),
        "net_pnl": round(final - initial_equity, 4),
        "return_pct": round((final / initial_equity - 1) * 100, 4),
        "max_drawdown_pct": round(dd * 100, 4),
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 4) if losses and sum(losses) < 0 else None,
        "gross_pnl": round(sum(t.gross_pnl for t in trades), 4),
        "fees": round(sum(t.fees for t in trades), 4),
        "funding": round(sum(t.funding for t in trades), 4),
        "ambiguous_bars": sum(t.ambiguous_bar for t in trades),
        "sharpe_hourly_annualized": round(sharpe, 4),
    }
