import pytest
from pydantic import ValidationError

from app.core.risk import PRESETS, RiskSettings, classify_change, preview


def test_defaults_match_prd():
    r = RiskSettings()
    assert (r.leverage, r.risk_per_trade_pct, r.daily_loss_pct, r.max_drawdown_pct) == (
        2,
        0.25,
        2,
        5,
    )
    assert r.capital_usage_pct == 100 and r.margin_mode == "isolated"


def test_hard_caps_reject():
    with pytest.raises(ValidationError):
        RiskSettings(leverage=10)
    with pytest.raises(ValidationError):
        RiskSettings(daily_loss_pct=3, max_drawdown_pct=2)
    with pytest.raises(ValidationError):
        RiskSettings(min_free_margin_pct=20)


def test_presets_valid():
    for p in PRESETS.values():
        RiskSettings(**p["values"])


def test_classify():
    base = RiskSettings()
    assert classify_change(base, RiskSettings(leverage=1))[0] == "decrease"
    assert classify_change(base, RiskSettings(leverage=3))[0] == "increase"
    assert classify_change(base, RiskSettings(min_free_margin_pct=40))[0] == "increase"
    assert classify_change(base, RiskSettings(leverage=3, capital_usage_pct=50))[0] == "mixed"


def test_preview_uses_capital_usage():
    p = preview(RiskSettings(capital_usage_pct=50), 1000)
    assert p["bot_capital"] == 500
    assert p["max_loss_per_trade"] == pytest.approx(1.25)
