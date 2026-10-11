import pandas as pd
import pytest

from app.backtest.engine import (
    CostModel,
    _Open,
    daily_universe,
    run_portfolio,
    size_order,
)
from app.backtest.splits import SplitSpec, split_bounds
from app.core.risk import RiskSettings
from app.strategies.base import SIGNAL_COLUMNS, Strategy, StrategyParams

ZERO = CostModel(taker_fee_bps=0, slippage_bps=0, min_notional=0)


class AlwaysLong(Strategy):
    """준비 후 매 봉 롱 진입 신호, 청산 신호 없음."""

    name, version, label, Params = "always", "0", "test", StrategyParams

    def warmup_bars(self):
        return 1

    def compute(self, df):
        out = df.copy()
        for c in SIGNAL_COLUMNS:
            out[c] = False
        out["entry_long"] = True
        out["atr"] = 1.0
        return out


def flat(n=48, price=100.0, start="2025-01-01", qv=1.0):
    return pd.DataFrame(
        {
            "open_time": pd.date_range(start, periods=n, freq="h", tz="UTC"),
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1.0,
            "quote_volume": qv,
        }
    )


# ---- size_order: 포트폴리오 한도 ----


def test_max_positions():
    opens = [_Open("A", "long", 10, 0.1), _Open("B", "long", 10, 0.1)]
    qty, why = size_order(1000, "C", "long", 100, 98, RiskSettings(), ZERO, opens)
    assert qty == 0 and why == "max_positions"


def test_total_risk_budget_shared():
    # 전체 계획 손실 0.5% = 5 USDT 중 4 USDT 사용 중 → 남은 1 USDT / 단위 손실 2 = 0.5
    risk = RiskSettings(max_positions=5)
    opens = [_Open("A", "long", 50, 4.0)]
    qty, _ = size_order(1000, "C", "long", 100, 98, risk, ZERO, opens)
    assert qty == pytest.approx(0.5)


def test_corr_group_risk_only_counts_correlated():
    risk = RiskSettings(max_positions=5, total_risk_pct=1.0)
    opens = [_Open("A", "long", 50, 3.0)]  # 그룹 한도 0.35% = 3.5 USDT
    q_corr, _ = size_order(1000, "B", "long", 100, 98, risk, ZERO, opens, {"A"})
    q_free, _ = size_order(1000, "B", "long", 100, 98, risk, ZERO, opens, set())
    assert q_corr == pytest.approx(0.25)  # (3.5-3)/2
    assert q_free == pytest.approx(1.25)  # 주문별 2.5/2


def test_net_exposure_allows_hedge():
    risk = RiskSettings(
        max_positions=5,
        net_exposure_x=1.0,
        gross_exposure_x=3.0,
        symbol_exposure_x=1.0,
        leverage=5,
        min_free_margin_pct=30,
    )
    opens = [_Open("A", "long", 1000, 0.0)]  # 순 익스포저 한도 소진
    q_long, why = size_order(1000, "B", "long", 100, 99.9, risk, ZERO, opens)
    q_short, _ = size_order(1000, "B", "short", 100, 100.1, risk, ZERO, opens)
    assert q_long == 0 and why == "net_exposure"
    assert q_short > 0


# ---- 포트폴리오 실행 ----


def test_correlated_symbols_share_group_budget():
    data = {"AAA": flat(), "BBB": flat()}  # 같은 가격 → 상관 1 (데이터 부족도 보수적으로 1)
    risk = RiskSettings(
        max_positions=5, total_risk_pct=1.0, corr_group_risk_pct=0.35, risk_per_trade_pct=0.25
    )
    res = run_portfolio(data, AlwaysLong(), risk, ZERO, 1000)
    first = {t.symbol: t for t in res.trades}
    # AAA가 먼저(코드 순) 0.25% 사용 → BBB는 그룹 잔여 0.10%만
    assert first["AAA"].planned_risk == pytest.approx(2.5, rel=1e-6)
    assert first["BBB"].planned_risk == pytest.approx(1.0, rel=1e-6)


def test_window_limits_trading():
    data = {"AAA": flat(96)}
    w = (pd.Timestamp("2025-01-02", tz="UTC"), pd.Timestamp("2025-01-03", tz="UTC"))
    res = run_portfolio(data, AlwaysLong(), RiskSettings(), ZERO, 1000, window=w)
    assert len(res.equity_curve) == 24
    assert all(w[0] <= pd.Timestamp(t.entry_time) < w[1] for t in res.trades)


def test_dynamic_universe_blocks_entries():
    data = {
        "AAA": flat(24 * 10, qv=100.0),
        "BBB": flat(24 * 10, qv=1.0),
    }
    uni = daily_universe(data, top_k=1, lookback_days=2)
    assert uni[pd.Timestamp("2025-01-01").date()] == []  # 직전 데이터 없음
    assert uni[pd.Timestamp("2025-01-05").date()] == ["AAA"]
    res = run_portfolio(data, AlwaysLong(), RiskSettings(), ZERO, 1000, universe=uni)
    assert {t.symbol for t in res.trades} == {"AAA"}
    assert res.skipped_signals.get("not_in_universe", 0) > 0


def test_universe_excludes_new_listing():
    data = {"OLD": flat(24 * 10, qv=1.0), "NEW": flat(24 * 3, start="2025-01-08", qv=1000.0)}
    uni = daily_universe(data, top_k=2, lookback_days=7)
    assert uni[pd.Timestamp("2025-01-10").date()] == ["OLD"]


def test_split_bounds_contiguous():
    a, b = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    s = split_bounds(a, b, SplitSpec())
    assert s["train"][0] == a and s["test"][1] == b
    assert s["train"][1] == s["validation"][0] and s["validation"][1] == s["test"][0]


def test_split_spec_sum():
    with pytest.raises(ValueError):
        SplitSpec(train=0.5, validation=0.2, test=0.2)
