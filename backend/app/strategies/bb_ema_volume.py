"""초기 전략: 볼린저 밴드 돌파 + EMA 추세 필터 + 거래량 확인 (PRD FR-02)."""

from typing import Literal

import pandas as pd
from pydantic import Field, model_validator

from app.strategies.base import Strategy, StrategyParams
from app.strategies.indicators import atr, bollinger, ema


class BbEmaVolumeParams(StrategyParams):
    bb_period: int = Field(20, ge=10, le=100)
    bb_stddev: float = Field(2.0, ge=1.0, le=4.0)
    ema_fast_period: int = Field(50, ge=10, le=200)
    ema_slow_period: int = Field(200, ge=50, le=500)
    volume_period: int = Field(20, ge=5, le=100)
    volume_multiplier: float = Field(1.5, ge=1.0, le=5.0)
    atr_period: int = Field(14, ge=5, le=100)
    stop_atr_multiple: float = Field(2.0, ge=1.0, le=5.0)
    take_profit_atr_multiple: float = Field(3.0, ge=1.0, le=10.0)
    exit_on_bb_middle: bool = True
    exit_on_ema_reversal: bool = True
    max_holding_bars: int = Field(48, ge=1, le=240)
    cooldown_bars: int = Field(2, ge=0, le=24)
    trade_direction: Literal["long", "short", "both"] = "both"
    warmup_multiplier: int = Field(5, ge=3, le=10)

    @model_validator(mode="after")
    def _fast_lt_slow(self):
        if self.ema_fast_period >= self.ema_slow_period:
            raise ValueError("ema_slow_period는 ema_fast_period보다 커야 합니다")
        return self


class BbEmaVolume(Strategy):
    name = "bb_ema_volume"
    version = "1.0.0"
    label = "볼린저 밴드 + EMA + 거래량 (1h 돌파)"
    Params = BbEmaVolumeParams
    params: BbEmaVolumeParams

    def warmup_bars(self) -> int:
        p = self.params
        return (
            max(p.bb_period, p.ema_slow_period, p.volume_period, p.atr_period) * p.warmup_multiplier
        )

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = df.copy()
        close = out["close"]
        lower, mid, upper = bollinger(close, p.bb_period, p.bb_stddev)
        ema_fast = ema(close, p.ema_fast_period)
        ema_slow = ema(close, p.ema_slow_period)
        out["bb_lower"], out["bb_mid"], out["bb_upper"] = lower, mid, upper
        out["ema_fast"], out["ema_slow"] = ema_fast, ema_slow
        out["atr"] = atr(out["high"], out["low"], close, p.atr_period)

        # 현재 봉을 제외한 직전 N봉 평균 거래대금 × 배수
        qv = out["quote_volume"]
        vol_avg = qv.shift(1).rolling(p.volume_period, min_periods=p.volume_period).mean()
        vol_ok = (vol_avg > 0) & (qv >= vol_avg * p.volume_multiplier)

        ready = pd.Series(False, index=out.index)
        ready.iloc[self.warmup_bars() - 1 :] = True
        ready &= out[["bb_mid", "ema_slow", "atr"]].notna().all(axis=1)

        long_ok = p.trade_direction in ("long", "both")
        short_ok = p.trade_direction in ("short", "both")

        out["entry_long"] = (
            long_ok
            & ready
            & vol_ok
            & (ema_fast > ema_slow)
            & (close > ema_fast)
            & (close > upper)
            & (close.shift(1) <= upper.shift(1))
        )
        out["entry_short"] = (
            short_ok
            & ready
            & vol_ok
            & (ema_fast < ema_slow)
            & (close < ema_fast)
            & (close < lower)
            & (close.shift(1) >= lower.shift(1))
        )

        exit_long = pd.Series(False, index=out.index)
        exit_short = pd.Series(False, index=out.index)
        if p.exit_on_bb_middle:
            exit_long |= close < mid
            exit_short |= close > mid
        if p.exit_on_ema_reversal:
            exit_long |= ema_fast < ema_slow
            exit_short |= ema_fast > ema_slow
        out["exit_long"] = exit_long & ready
        out["exit_short"] = exit_short & ready
        return out
