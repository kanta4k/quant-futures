import pandas as pd
import pytest

from app.backtest.engine import CostModel, run_backtest, size_position
from app.core.risk import RiskSettings
from app.strategies.base import SIGNAL_COLUMNS, Strategy, StrategyParams
from app.strategies.bb_ema_volume import BbEmaVolume, BbEmaVolumeParams


class Scripted(Strategy):
    """지정한 봉에서 롱 진입 신호만 내는 테스트용 전략."""

    name, version, label, Params = "scripted", "0", "test", StrategyParams

    def __init__(self, entries, atr_value, **kw):
        super().__init__(StrategyParams(**kw))
        self.entries, self.atr_value = entries, atr_value

    def warmup_bars(self):
        return 1

    def compute(self, df):
        out = df.copy()
        for c in SIGNAL_COLUMNS:
            out[c] = False
        out["atr"] = self.atr_value
        out.loc[self.entries, "entry_long"] = True
        return out


def bars(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = pd.date_range("2025-01-01", periods=len(df), freq="h", tz="UTC")
    df["volume"] = 1.0
    df["quote_volume"] = 1.0
    return df


ZERO = CostModel(taker_fee_bps=0, slippage_bps=0, min_notional=0)
LOOSE = RiskSettings(risk_per_trade_pct=0.5, total_risk_pct=1.0, corr_group_risk_pct=0.5)


def test_fill_next_open_and_take_profit():
    df = bars(
        [[100, 101, 99, 100], [102, 103, 101, 102], [102, 120, 101, 110], [110, 111, 109, 110]]
    )
    res = run_backtest(df, Scripted([0], 2.0), LOOSE, ZERO, 1000)
    t = res.trades[0]
    assert t.entry_price == 102  # 신호 봉 종가(100)가 아니라 다음 봉 시가
    assert t.stop == 98 and t.take_profit == 108
    assert t.exit_reason == "take_profit" and t.exit_price == 108


def test_same_bar_stop_and_tp_is_conservative():
    df = bars(
        [[100, 101, 99, 100], [100, 100, 100, 100], [100, 110, 90, 100], [100, 100, 100, 100]]
    )
    res = run_backtest(df, Scripted([0], 2.0), LOOSE, ZERO, 1000)
    t = res.trades[0]
    assert t.exit_reason == "stop" and t.ambiguous_bar
    assert res.metrics["ambiguous_bars"] == 1


def test_gap_through_stop_fills_at_open():
    df = bars([[100, 101, 99, 100], [100, 100, 100, 100], [90, 91, 89, 90], [90, 90, 90, 90]])
    t = run_backtest(df, Scripted([0], 2.0), LOOSE, ZERO, 1000).trades[0]
    assert t.exit_reason == "stop_gap" and t.exit_price == 90


def test_risk_sizing_limits_loss():
    risk = RiskSettings()  # 주문별 0.25%
    qty, _ = size_position(1000, 100, 98, risk, ZERO)
    assert qty * 2 == pytest.approx(2.5)  # 1000 × 0.25%


def test_capital_usage_scales_size():
    full, _ = size_position(1000, 100, 98, RiskSettings(), ZERO)
    half, _ = size_position(1000, 100, 98, RiskSettings(capital_usage_pct=50), ZERO)
    assert half == pytest.approx(full / 2)


def test_min_notional_never_rounds_up():
    qty, why = size_position(100, 100, 50, RiskSettings(), CostModel(min_notional=5))
    assert qty == 0 and why == "below_min_notional"


def test_fees_and_funding_reduce_pnl():
    df = bars([[100, 101, 99, 100], [100, 100, 100, 100], [100, 100, 100, 100]])
    df["funding_rate"] = [float("nan"), float("nan"), 0.001]
    cost = CostModel(taker_fee_bps=5, slippage_bps=0, min_notional=0)
    t = run_backtest(df, Scripted([0], 2.0), LOOSE, cost, 1000).trades[0]
    assert t.fees > 0 and t.funding < 0
    assert t.net_pnl == pytest.approx(t.gross_pnl - t.fees + t.funding)


def test_full_strategy_runs(synthetic_ohlcv):
    s = BbEmaVolume(BbEmaVolumeParams(ema_fast_period=20, ema_slow_period=60, warmup_multiplier=3))
    res = run_backtest(synthetic_ohlcv, s, RiskSettings(), CostModel(), 500)
    assert res.metrics["trades"] > 0
    assert len(res.equity_curve) == len(synthetic_ohlcv)
    # 동일 입력 → 동일 결과 (재현성)
    res2 = run_backtest(synthetic_ohlcv, s, RiskSettings(), CostModel(), 500)
    assert res.metrics == res2.metrics
