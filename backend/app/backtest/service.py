"""백테스트 실행 서비스 — 요청 검증, 데이터 로드, 구간 분리, 파라미터 탐색."""

import itertools
import threading
import time
import uuid
from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.backtest.engine import (
    BacktestResult,
    CostModel,
    PortfolioOptions,
    daily_universe,
    run_portfolio,
)
from app.backtest.splits import SplitSpec, split_bounds
from app.core.risk import RiskSettings
from app.data import binance_public as market
from app.strategies import get_strategy
from app.strategies.base import Strategy

MAX_CURVE_POINTS = 3000


class UniverseSpec(BaseModel):
    mode: Literal["fixed", "dynamic"] = "fixed"
    top_k: int = Field(5, ge=1, le=20)
    lookback_days: int = Field(7, ge=1, le=60)


class BacktestRequest(BaseModel):
    strategy: str = "bb_ema_volume"
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT"], min_length=1, max_length=40)
    interval: str = "1h"
    params: dict = Field(default_factory=dict)
    risk: dict | None = None  # 없으면 현재 리스크 설정 버전 사용
    cost: CostModel = Field(default_factory=CostModel)
    portfolio: PortfolioOptions = Field(default_factory=PortfolioOptions)
    universe: UniverseSpec = Field(default_factory=UniverseSpec)
    split: SplitSpec | None = Field(default_factory=SplitSpec)
    initial_equity: float = Field(500.0, gt=0)
    apply_loss_limits: bool = True  # 일일 손실·누적 낙폭 잠금 적용 여부
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _single_symbol(cls, v):
        if isinstance(v, dict) and "symbol" in v and "symbols" not in v:
            v = {**v, "symbols": [v.pop("symbol")]}
        return v

    @model_validator(mode="after")
    def _normalize(self):
        self.symbols = sorted({s.upper() for s in self.symbols})
        return self


class Prepared:
    """로드된 데이터와 전략·리스크 — 같은 요청으로 여러 구간·파라미터를 돌릴 때 재사용."""

    def __init__(self, req: BacktestRequest, risk_values: dict):
        self.req = req
        cls = get_strategy(req.strategy)
        self.strategy_cls = cls
        self.strategy: Strategy = cls(cls.Params(**req.params))
        self.risk = RiskSettings(**(req.risk or risk_values))
        self.data = {s: market.load_dataset(s, req.interval) for s in req.symbols}
        self.universe = (
            daily_universe(self.data, req.universe.top_k, req.universe.lookback_days)
            if req.universe.mode == "dynamic"
            else None
        )
        self.start, self.end = self._period(self.strategy)

    def _period(self, strategy: Strategy) -> tuple[pd.Timestamp, pd.Timestamp]:
        warm = strategy.warmup_bars()
        ready = [df["open_time"].iloc[warm - 1] for df in self.data.values() if len(df) >= warm]
        if not ready:
            raise ValueError(f"모든 종목의 봉 수가 준비 봉({warm})보다 적습니다")
        first = min(ready)  # 가장 먼저 지표가 준비되는 종목 기준
        last = max(df["open_time"].iloc[-1] for df in self.data.values()) + pd.Timedelta(hours=1)
        start = max(first, pd.Timestamp(self.req.start)) if self.req.start else first
        end = min(last, pd.Timestamp(self.req.end)) if self.req.end else last
        if start >= end:
            raise ValueError("선택한 기간에 거래 가능한 봉이 없습니다")
        return start, end

    def run(
        self,
        window: tuple[pd.Timestamp, pd.Timestamp],
        strategy: Strategy | None = None,
        computed: dict | None = None,
    ) -> BacktestResult:
        r = self.req
        return run_portfolio(
            self.data,
            strategy or self.strategy,
            self.risk,
            r.cost,
            r.initial_equity,
            r.apply_loss_limits,
            window=window,
            universe=self.universe,
            options=r.portfolio,
            computed=computed,
        )


def downsample(curve: list[dict], n: int = MAX_CURVE_POINTS) -> list[dict]:
    if len(curve) <= n:
        return curve
    step = len(curve) / n
    picked = [curve[int(i * step)] for i in range(n)]
    picked[-1] = curve[-1]
    return picked


def run_request(prep: Prepared) -> dict:
    """전체 구간 + (설정 시) 학습/검증/최종 평가 구간을 각각 새 계좌로 실행한다."""
    computed = {s: prep.strategy.compute(df).reset_index(drop=True) for s, df in prep.data.items()}
    full = prep.run((prep.start, prep.end), computed=computed).to_dict()
    full["equity_curve"] = downsample(full["equity_curve"])
    segments = {}
    if prep.req.split is not None:
        for name, (a, b) in split_bounds(prep.start, prep.end, prep.req.split).items():
            seg = prep.run((a, b), computed=computed)
            segments[name] = {
                "start": a.isoformat(),
                "end": b.isoformat(),
                "metrics": seg.metrics,
                "by_symbol": seg.by_symbol,
                "skipped_signals": seg.skipped_signals,
            }
    return {
        **full,
        "segments": segments,
        "period": {"start": prep.start.isoformat(), "end": prep.end.isoformat()},
        "universe_mode": prep.req.universe.mode,
    }


# ---------------------------------------------------------------------------
# 파라미터 탐색 (학습·검증 구간만 사용, 최종 평가 구간은 보지 않음)
# ---------------------------------------------------------------------------

Objective = Literal["sharpe", "return_pct", "profit_factor", "return_over_dd"]
MAX_COMBOS = 200


class OptimizeRequest(BaseModel):
    base: BacktestRequest = Field(default_factory=BacktestRequest)
    grid: dict[str, list] = Field(default_factory=dict)
    objective: Objective = "sharpe"
    min_trades: int = Field(10, ge=0, description="검증 구간 최소 거래 수 (미달 시 순위 제외)")

    @model_validator(mode="after")
    def _check(self):
        if not self.grid:
            raise ValueError("탐색할 파라미터(grid)를 하나 이상 지정하세요")
        n = 1
        for k, vals in self.grid.items():
            if not vals:
                raise ValueError(f"{k}: 값 목록이 비어 있습니다")
            n *= len(vals)
        if n > MAX_COMBOS:
            raise ValueError(f"조합 수 {n}개 — 최대 {MAX_COMBOS}개까지 가능합니다")
        if self.base.split is None:
            raise ValueError("파라미터 탐색에는 구간 분리(split)가 필요합니다")
        return self


def score(metrics: dict, objective: Objective) -> float:
    if objective == "sharpe":
        return metrics["sharpe_hourly_annualized"]
    if objective == "return_pct":
        return metrics["return_pct"]
    if objective == "profit_factor":
        return metrics["profit_factor"] or 0.0
    dd = metrics["max_drawdown_pct"]
    return metrics["return_pct"] / dd if dd > 0 else metrics["return_pct"]


class Job:
    def __init__(self, total: int):
        self.id = uuid.uuid4().hex[:12]
        self.status: Literal["running", "done", "error"] = "running"
        self.total = total
        self.done = 0
        self.results: list[dict] = []
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None

    def view(self, objective: Objective, min_trades: int) -> dict:
        eligible = [r for r in self.results if r["validation"]["trades"] >= min_trades and r["ok"]]
        ranked = sorted(eligible, key=lambda r: r["score"], reverse=True)
        rest = [r for r in self.results if r not in eligible]
        return {
            "id": self.id,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "error": self.error,
            "elapsed_sec": round((self.finished or time.time()) - self.started, 1),
            "objective": objective,
            "ranked": ranked,
            "excluded": rest,
        }


JOBS: dict[str, tuple[Job, OptimizeRequest]] = {}


def start_optimize(req: OptimizeRequest, risk_values: dict) -> Job:
    keys = list(req.grid)
    combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*req.grid.values())]
    prep = Prepared(req.base, risk_values)  # 데이터 로드·검증은 요청 스레드에서 (오류 즉시 반환)
    # 모든 조합의 파라미터 유효성 먼저 확인
    for c in combos:
        prep.strategy_cls.Params(**{**req.base.params, **c})
    bounds = split_bounds(prep.start, prep.end, req.base.split)
    job = Job(len(combos))
    JOBS[job.id] = (job, req)

    def work():
        try:
            for c in combos:
                params = prep.strategy_cls.Params(**{**req.base.params, **c})
                strat = prep.strategy_cls(params)
                computed = {
                    s: strat.compute(df).reset_index(drop=True) for s, df in prep.data.items()
                }
                train = prep.run(bounds["train"], strat, computed).metrics
                val = (
                    prep.run(bounds["validation"], strat, computed).metrics
                    if "validation" in bounds
                    else train
                )
                job.results.append(
                    {
                        "params": c,
                        "train": train,
                        "validation": val,
                        "score": score(val, req.objective),
                        "ok": True,
                    }
                )
                job.done += 1
            job.status = "done"
        except Exception as e:  # 백그라운드 작업 실패를 상태로 노출
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
        finally:
            job.finished = time.time()

    threading.Thread(target=work, daemon=True).start()
    return job
