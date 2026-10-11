import os
import tempfile

import numpy as np
import pandas as pd
import pytest

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("DATA_DIR", f"{_tmp}/market")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-pass")


@pytest.fixture
def synthetic_ohlcv():
    """추세 + 노이즈가 섞인 1h 합성 데이터 (네트워크 없이 테스트)."""
    rng = np.random.default_rng(7)
    n = 3000
    trend = np.concatenate([np.linspace(0, 0.6, n // 2), np.linspace(0.6, 0.1, n - n // 2)])
    close = 30000 * np.exp(trend + np.cumsum(rng.normal(0, 0.006, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    qv = rng.lognormal(18, 0.5, n)
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": qv / close,
            "quote_volume": qv,
        }
    )
