"""포트폴리오 봉 기반 백테스트 엔진 (PRD FR-03, FR-08, FR-15).

여러 종목을 하나의 계좌로 동시에 시뮬레이션한다. 종목이 하나면 단일 종목 백테스트가 된다.

체결 가정:
- t봉 마감 신호 → t+1봉 시가에 체결 (신호 봉 종가 소급 체결 금지)
- 진입·지표 청산은 시가 ± 슬리피지, 수수료는 테이커 기준 양방향
- 손절·익절은 진입 체결가와 신호 봉 ATR로 고정. 같은 봉에서 둘 다 닿으면 손절 우선(보수적)
- 시가가 손절선을 넘어 갭이 나면 시가에 손절 체결
- 펀딩: funding_rate 열이 있으면 해당 봉 시각에 포지션 명목가치 × 요율 반영 (롱 지불 / 숏 수취)

포트폴리오 규칙:
- 같은 시각 진입 신호는 유니버스 거래대금 순위 → 종목 코드 순으로 처리 (재현성)
- 수량은 주문별 위험, 전체 위험, 종목·총·순 익스포저, 증거금, 상관 그룹 한도 중 가장 엄격한 값
- 상관 그룹: 진입 시점 직전 `corr_lookback_bars`봉 수익률의 |상관계수| ≥ 임계값인 보유 종목
- 유니버스에서 빠진 종목은 신규 진입만 막고 기존 포지션은 청산 규칙대로 관리 (PRD A-34)
- 지표는 전체 데이터로 계산(인과적)하고, 거래는 window 구간에서만 한다 → 구간 분리 시 준비 봉 확보
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import date

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


class PortfolioOptions(BaseModel):
    corr_lookback_bars: int = Field(720, ge=24, le=5000, description="상관계수 계산 봉 수")
    corr_threshold: float = Field(0.8, ge=0.0, le=1.0, description="상관 그룹 |ρ| 임계값")


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: str
    entry_price: float
    qty: float
    stop: float
    take_profit: float
    planned_risk: float = 0.0
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
    by_symbol: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _plain(
            {
                "trades": [asdict(t) for t in self.trades],
                "equity_curve": self.equity_curve,
                "metrics": self.metrics,
                "skipped_signals": self.skipped_signals,
                "by_symbol": self.by_symbol,
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


def per_unit_loss(entry: float, stop: float, cost: CostModel) -> float:
    """손절 시 단위 수량당 손실: 가격 차이 + 진입·청산 수수료 + 청산 슬리피지 완충분."""
    return abs(entry - stop) + entry * (2 * cost.taker_fee_bps + cost.slippage_bps) / 1e4


@dataclass
class _Open:
    """사이징에 필요한 보유 포지션 요약."""

    symbol: str
    side: str
    notional: float
    planned_risk: float


def size_order(
    equity: float,
    symbol: str,
    side: str,
    entry: float,
    stop: float,
    risk: RiskSettings,
    cost: CostModel,
    open_positions: list[_Open] | None = None,
    correlated: set[str] | None = None,
) -> tuple[float, str]:
    """계좌·포트폴리오 한도를 모두 만족하는 최대 수량. (qty, 거부 사유)

    거부 사유는 수량을 0(또는 최소 주문금액 미만)으로 만든 가장 엄격한 한도 이름이다.
    """
    opens = open_positions or []
    correlated = correlated or set()
    e_bot = equity * risk.capital_usage_pct / 100
    if len(opens) >= risk.max_positions:
        return 0.0, "max_positions"
    unit_loss = per_unit_loss(entry, stop, cost)
    if unit_loss <= 0 or e_bot <= 0:
        return 0.0, "invalid_stop"

    gross = sum(p.notional for p in opens)
    net = sum(p.notional if p.side == "long" else -p.notional for p in opens)
    total_risk = sum(p.planned_risk for p in opens)
    group = [p for p in opens if p.symbol in correlated]
    group_notional = sum(p.notional for p in group)
    group_risk = sum(p.planned_risk for p in group)
    net_room = e_bot * risk.net_exposure_x - (net if side == "long" else -net)

    caps = {
        "risk_per_trade": e_bot * risk.risk_per_trade_pct / 100 / unit_loss,
        "total_risk": (e_bot * risk.total_risk_pct / 100 - total_risk) / unit_loss,
        "corr_group_risk": (e_bot * risk.corr_group_risk_pct / 100 - group_risk) / unit_loss,
        "symbol_exposure": e_bot * risk.symbol_exposure_x / entry,
        "gross_exposure": (e_bot * risk.gross_exposure_x - gross) / entry,
        "net_exposure": net_room / entry,
        "corr_group_exposure": (e_bot * risk.corr_group_exposure_x - group_notional) / entry,
        "margin": (e_bot * risk.leverage * (1 - risk.min_free_margin_pct / 100) - gross) / entry,
    }
    binding = min(caps, key=caps.get)
    qty = _round_down(max(caps[binding], 0.0), cost.qty_step)
    if qty <= 0 or qty * entry < cost.min_notional:
        # 최소 주문을 맞추려고 위험 예산을 넘겨 올림하지 않는다 (PRD FR-08, FR-19)
        return 0.0, "below_min_notional" if binding == "risk_per_trade" else binding
    return qty, ""


def size_position(
    equity: float, entry: float, stop: float, risk: RiskSettings, cost: CostModel
) -> tuple[float, str]:
    """보유 포지션이 없을 때의 단일 주문 수량."""
    side = "long" if stop < entry else "short"
    return size_order(equity, "", side, entry, stop, risk, cost)


class _Sym:
    """종목별 신호·가격 배열과 타임라인 매핑."""

    def __init__(self, name: str, df: pd.DataFrame, timeline: np.ndarray):
        self.name = name
        times = df["open_time"].to_numpy(dtype="datetime64[ns]")
        self.times = times
        self.o = df["open"].to_numpy(float)
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.atr = df["atr"].to_numpy(float)
        self.entry_long = df["entry_long"].to_numpy(bool)
        self.entry_short = df["entry_short"].to_numpy(bool)
        self.exit_long = df["exit_long"].to_numpy(bool)
        self.exit_short = df["exit_short"].to_numpy(bool)
        self.funding = (
            df["funding_rate"].to_numpy(float)
            if "funding_rate" in df.columns
            else np.full(len(df), np.nan)
        )
        # 타임라인 인덱스 → 종목 행 인덱스 (-1: 해당 시각 봉 없음)
        idx = np.searchsorted(times, timeline)
        idx_clipped = np.minimum(idx, len(times) - 1)
        self.row = np.where(times[idx_clipped] == timeline, idx_clipped, -1)


def _naive_utc(ts) -> np.datetime64:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return np.datetime64(t, "ns")


def build_timeline(data: dict[str, pd.DataFrame]) -> np.ndarray:
    times = np.concatenate([d["open_time"].to_numpy(dtype="datetime64[ns]") for d in data.values()])
    return np.unique(times)


def daily_universe(
    data: dict[str, pd.DataFrame], top_k: int, lookback_days: int = 7
) -> dict[date, list[str]]:
    """일자별 유니버스: 직전 `lookback_days`개 완료 일의 거래대금 합계 상위 `top_k` (PRD FR-15).

    직전 기간 데이터가 다 차지 않은 종목(신규 상장 등)은 제외한다.
    """
    daily = {}
    for sym, df in data.items():
        s = df.set_index("open_time")["quote_volume"].resample("1D").agg(["sum", "count"])
        full_day = s["count"] >= 20  # 1h 기준 거의 완전한 하루
        vol = s["sum"].where(full_day)
        # d일의 유니버스는 d-1일까지의 완료 데이터만 사용
        daily[sym] = vol.rolling(lookback_days, min_periods=lookback_days).sum().shift(1)
    table = pd.DataFrame(daily)
    out: dict[date, list[str]] = {}
    for ts, row in table.iterrows():
        ranked = row.dropna().sort_values(ascending=False, kind="stable")
        out[pd.Timestamp(ts).date()] = list(ranked.index[:top_k])
    return out


def run_portfolio(
    data: dict[str, pd.DataFrame],
    strategy: Strategy,
    risk: RiskSettings,
    cost: CostModel,
    initial_equity: float = 500.0,
    apply_loss_limits: bool = True,
    window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    universe: dict[date, list[str]] | None = None,
    options: PortfolioOptions | None = None,
    computed: dict[str, pd.DataFrame] | None = None,
) -> BacktestResult:
    """`computed`에 strategy.compute() 결과를 넘기면 재계산을 건너뛴다 (구간 분리·탐색용)."""
    opts = options or PortfolioOptions()
    p = strategy.params
    fee = cost.taker_fee_bps / 1e4
    slip = cost.slippage_bps / 1e4

    frames = computed or {s: strategy.compute(df).reset_index(drop=True) for s, df in data.items()}
    full_timeline = build_timeline(frames)
    syms = {s: _Sym(s, df, full_timeline) for s, df in sorted(frames.items())}

    # 상관계수용 수익률 행렬 (전체 타임라인 기준)
    closes = np.full((len(full_timeline), len(syms)), np.nan)
    col = {}
    for j, (s, sd) in enumerate(syms.items()):
        col[s] = j
        mask = sd.row >= 0
        closes[mask, j] = sd.c[sd.row[mask]]
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.diff(np.log(closes), axis=0, prepend=np.nan)
    corr_cache: dict[tuple[str, str, int], float] = {}

    def corr(a: str, b: str, k: int) -> float:
        key = (min(a, b), max(a, b), k // 24)  # 하루 단위 캐시
        if key not in corr_cache:
            lo = max(0, k - opts.corr_lookback_bars + 1)
            x, y = rets[lo : k + 1, col[a]], rets[lo : k + 1, col[b]]
            ok = ~(np.isnan(x) | np.isnan(y))
            if ok.sum() < opts.corr_lookback_bars // 2 or x[ok].std() == 0 or y[ok].std() == 0:
                corr_cache[key] = 1.0  # 데이터 부족 → 보수적으로 같은 그룹
            else:
                corr_cache[key] = float(np.corrcoef(x[ok], y[ok])[0, 1])
        return corr_cache[key]

    start_k, end_k = 0, len(full_timeline)
    if window is not None:
        w0, w1 = window
        if w0 is not None:
            start_k = int(np.searchsorted(full_timeline, _naive_utc(w0), "left"))
        if w1 is not None:
            end_k = int(np.searchsorted(full_timeline, _naive_utc(w1), "left"))
    if start_k >= end_k:
        raise ValueError("백테스트 구간에 봉이 없습니다")

    result = BacktestResult()
    skipped: dict[str, int] = {}
    cash = initial_equity
    positions: dict[str, Trade] = {}
    entry_row: dict[str, int] = {}
    last_px: dict[str, float] = {}
    cooldown_until: dict[str, int] = {}
    pending: dict[str, tuple[str, float]] = {}  # symbol → (동작, 신호 봉 ATR)
    peak = equity = initial_equity
    daily_start_equity = initial_equity
    current_day = None
    locked_until_day = None
    dd_locked = False
    order_by_rank = list(syms)

    def skip(reason: str):
        skipped[reason] = skipped.get(reason, 0) + 1

    def ts_str(sd: _Sym, r: int) -> str:
        return str(pd.Timestamp(sd.times[r], tz="UTC"))

    def close_pos(sd: _Sym, r: int, price: float, reason: str, ambiguous: bool = False):
        nonlocal cash
        pos = positions.pop(sd.name)
        sign = 1 if pos.side == "long" else -1
        exit_fee = price * pos.qty * fee
        pos.exit_time = ts_str(sd, r)
        pos.exit_price = price
        pos.exit_reason = reason
        pos.gross_pnl = sign * (price - pos.entry_price) * pos.qty
        pos.fees += exit_fee
        pos.net_pnl = pos.gross_pnl - pos.fees + pos.funding
        pos.bars_held = r - entry_row.pop(sd.name)
        pos.ambiguous_bar = pos.ambiguous_bar or ambiguous
        cash += pos.gross_pnl - exit_fee
        result.trades.append(pos)
        cooldown_until[sd.name] = r + p.cooldown_bars

    def open_summary() -> list[_Open]:
        return [
            _Open(s, t.side, t.qty * last_px.get(s, t.entry_price), t.planned_risk)
            for s, t in positions.items()
        ]

    for k in range(start_k, end_k):
        day = pd.Timestamp(full_timeline[k]).date()
        if day != current_day:
            current_day = day
            daily_start_equity = equity
            if universe is not None:
                ranked = universe.get(day, [])
                order_by_rank = ranked + sorted(s for s in syms if s not in ranked)
        active = [(s, syms[s]) for s in order_by_rank if syms[s].row[k] >= 0]

        # 1) 시가: 대기 청산 → 대기 진입 (순위 순)
        for s, sd in active:
            r = sd.row[k]
            last_px[s] = sd.o[r]
            act = pending.get(s)
            if act and act[0].startswith("exit") and s in positions:
                pos = positions[s]
                px = sd.o[r] * (1 - slip) if pos.side == "long" else sd.o[r] * (1 + slip)
                close_pos(sd, r, px, act[0].split(":", 1)[1])
                del pending[s]
        for s, sd in active:
            act = pending.pop(s, None)
            if not act or act[0] not in ("long", "short") or s in positions:
                continue
            side, atr_val = act
            r = sd.row[k]
            px = sd.o[r] * (1 + slip) if side == "long" else sd.o[r] * (1 - slip)
            dist, tp_dist = p.stop_atr_multiple * atr_val, p.take_profit_atr_multiple * atr_val
            stop = px - dist if side == "long" else px + dist
            tp = px + tp_dist if side == "long" else px - tp_dist
            opens = open_summary()
            correlated = {
                o.symbol for o in opens if abs(corr(s, o.symbol, k)) >= opts.corr_threshold
            }
            mark_equity = cash + sum(
                (1 if t.side == "long" else -1) * (last_px[o] - t.entry_price) * t.qty
                for o, t in positions.items()
            )
            qty, why = size_order(mark_equity, s, side, px, stop, risk, cost, opens, correlated)
            if qty <= 0:
                skip(why)
                continue
            positions[s] = Trade(
                s,
                side,
                ts_str(sd, r),
                px,
                qty,
                stop,
                tp,
                planned_risk=qty * per_unit_loss(px, stop, cost),
                fees=px * qty * fee,
            )
            entry_row[s] = r
            cash -= px * qty * fee

        # 2) 펀딩, 3) 봉 내부 손절·익절
        for s, sd in active:
            if s not in positions:
                continue
            r, pos = sd.row[k], positions[s]
            if not np.isnan(sd.funding[r]):
                amt = -(1 if pos.side == "long" else -1) * pos.qty * sd.o[r] * sd.funding[r]
                pos.funding += amt
                cash += amt
            o, h, lo = sd.o[r], sd.h[r], sd.l[r]
            if pos.side == "long":
                hit_sl, hit_tp = lo <= pos.stop, h >= pos.take_profit
                if o <= pos.stop:
                    close_pos(sd, r, o * (1 - slip), "stop_gap")
                elif hit_sl:
                    close_pos(sd, r, pos.stop * (1 - slip), "stop", ambiguous=hit_tp)
                elif hit_tp:
                    close_pos(sd, r, pos.take_profit, "take_profit")
            else:
                hit_sl, hit_tp = h >= pos.stop, lo <= pos.take_profit
                if o >= pos.stop:
                    close_pos(sd, r, o * (1 + slip), "stop_gap")
                elif hit_sl:
                    close_pos(sd, r, pos.stop * (1 + slip), "stop", ambiguous=hit_tp)
                elif hit_tp:
                    close_pos(sd, r, pos.take_profit, "take_profit")

        # 4) 봉 마감 평가자산·손실 한도 (PRD FR-09)
        for s, sd in active:
            last_px[s] = sd.c[sd.row[k]]
        gross = 0.0
        unreal = 0.0
        for s, t in positions.items():
            unreal += (1 if t.side == "long" else -1) * (last_px[s] - t.entry_price) * t.qty
            gross += t.qty * last_px[s]
        equity = cash + unreal
        peak = max(peak, equity)
        if peak - equity >= peak * risk.capital_usage_pct / 100 * risk.max_drawdown_pct / 100:
            dd_locked = True
        day_base = daily_start_equity * risk.capital_usage_pct / 100
        if daily_start_equity - equity >= day_base * risk.daily_loss_pct / 100:
            locked_until_day = day
        locked = apply_loss_limits and (dd_locked or locked_until_day == day)
        result.equity_curve.append(
            {
                "time": str(pd.Timestamp(full_timeline[k], tz="UTC")),
                "equity": round(equity, 6),
                "gross_exposure": round(gross, 4),
                "positions": len(positions),
                "locked": locked,
            }
        )

        # 5) 다음 봉 동작 결정
        allowed = set(universe.get(day, [])) if universe is not None else None
        for s, sd in active:
            r = sd.row[k]
            if s in positions:
                pos = positions[s]
                if locked:
                    pending[s] = ("exit:risk_lock", 0.0)
                elif (pos.side == "long" and sd.exit_long[r]) or (
                    pos.side == "short" and sd.exit_short[r]
                ):
                    pending[s] = ("exit:signal", 0.0)
                elif r + 1 - entry_row[s] >= p.max_holding_bars:
                    pending[s] = ("exit:max_holding", 0.0)
                continue
            if not (sd.entry_long[r] or sd.entry_short[r]):
                continue
            if locked:
                skip("risk_locked")
            elif allowed is not None and s not in allowed:
                skip("not_in_universe")
            elif r < cooldown_until.get(s, -1):
                skip("cooldown")
            else:
                pending[s] = ("long" if sd.entry_long[r] else "short", sd.atr[r])

    # 구간 끝: 남은 포지션은 마지막 종가로 정리
    for s in list(positions):
        sd = syms[s]
        rows = sd.row[start_k:end_k]
        r = int(rows[rows >= 0][-1])
        close_pos(sd, r, sd.c[r], "end_of_data")
    if result.equity_curve:
        result.equity_curve[-1]["equity"] = round(cash, 6)
        result.equity_curve[-1]["gross_exposure"] = 0.0
        result.equity_curve[-1]["positions"] = 0

    result.skipped_signals = skipped
    result.metrics = _plain(compute_metrics(result, initial_equity))
    result.by_symbol = _plain(symbol_breakdown(result.trades))
    return result


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    risk: RiskSettings,
    cost: CostModel,
    initial_equity: float = 500.0,
    apply_loss_limits: bool = True,
    symbol: str = "SYMBOL",
) -> BacktestResult:
    """단일 종목 백테스트 = 종목 1개짜리 포트폴리오."""
    return run_portfolio({symbol: df}, strategy, risk, cost, initial_equity, apply_loss_limits)


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
    in_market = (
        sum(1 for e in result.equity_curve if e.get("positions", 0) > 0) / len(result.equity_curve)
        if result.equity_curve
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
        "time_in_market_pct": round(in_market * 100, 2),
        "sharpe_hourly_annualized": round(sharpe, 4),
        "start": result.equity_curve[0]["time"] if result.equity_curve else None,
        "end": result.equity_curve[-1]["time"] if result.equity_curve else None,
    }


def symbol_breakdown(trades: list[Trade]) -> dict:
    out: dict[str, dict] = {}
    for t in trades:
        b = out.setdefault(t.symbol, {"trades": 0, "wins": 0, "net_pnl": 0.0, "fees": 0.0})
        b["trades"] += 1
        b["wins"] += t.net_pnl > 0
        b["net_pnl"] += t.net_pnl
        b["fees"] += t.fees
    for b in out.values():
        b["win_rate_pct"] = round(b.pop("wins") / b["trades"] * 100, 2)
        b["net_pnl"] = round(b["net_pnl"], 4)
        b["fees"] = round(b["fees"], 4)
    return out
