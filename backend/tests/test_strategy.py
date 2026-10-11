import pandas as pd

from app.strategies.bb_ema_volume import BbEmaVolume, BbEmaVolumeParams
from app.strategies.indicators import atr, bollinger


def test_no_signal_before_warmup(synthetic_ohlcv):
    s = BbEmaVolume()
    out = s.compute(synthetic_ohlcv)
    w = s.warmup_bars()
    assert not out[["entry_long", "entry_short"]].iloc[: w - 1].any().any()


def test_signals_are_causal(synthetic_ohlcv):
    """미래 봉을 잘라내도 과거 신호가 바뀌지 않아야 한다."""
    s = BbEmaVolume(BbEmaVolumeParams(ema_fast_period=20, ema_slow_period=60, warmup_multiplier=3))
    full = s.compute(synthetic_ohlcv)
    cut = s.compute(synthetic_ohlcv.iloc[:2000])
    cols = ["entry_long", "entry_short", "exit_long", "exit_short"]
    pd.testing.assert_frame_equal(full[cols].iloc[:2000], cut[cols])


def test_long_entry_conditions(synthetic_ohlcv):
    s = BbEmaVolume(BbEmaVolumeParams(ema_fast_period=20, ema_slow_period=60, warmup_multiplier=3))
    out = s.compute(synthetic_ohlcv)
    longs = out[out["entry_long"]]
    assert len(longs) > 0
    assert (longs["close"] > longs["bb_upper"]).all()
    assert (longs["ema_fast"] > longs["ema_slow"]).all()


def test_bollinger_population_std():
    close = pd.Series([1.0, 2.0, 3.0, 4.0])
    _, mid, up = bollinger(close, 4, 1.0)
    assert mid.iloc[-1] == 2.5
    assert up.iloc[-1] - mid.iloc[-1] == close.std(ddof=0)


def test_atr_positive(synthetic_ohlcv):
    a = atr(synthetic_ohlcv["high"], synthetic_ohlcv["low"], synthetic_ohlcv["close"], 14)
    assert (a.dropna() > 0).all()
