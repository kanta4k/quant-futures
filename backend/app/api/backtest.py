from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.risk import current_version
from app.backtest.engine import CostModel, run_backtest
from app.core.risk import RiskSettings
from app.data import binance_public as market
from app.db import BacktestRun, get_session
from app.strategies import REGISTRY, get_strategy

router = APIRouter(prefix="/api", tags=["backtest"])


@router.get("/strategies")
def list_strategies():
    return [
        {
            "name": s.name,
            "version": s.version,
            "label": s.label,
            "params_schema": s.Params.model_json_schema(),
            "defaults": s.Params().model_dump(),
        }
        for s in REGISTRY.values()
    ]


@router.get("/data/datasets")
def datasets():
    return market.list_datasets()


@router.get("/data/universe")
def universe(n: int = 5):
    try:
        return market.top_symbols_by_quote_volume(n)
    except Exception as e:  # 네트워크 차단 등
        raise HTTPException(502, f"Binance 조회 실패: {type(e).__name__}") from None


class DownloadIn(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    start: datetime
    end: datetime


@router.post("/data/download")
def download(body: DownloadIn):
    try:
        return market.download_dataset(body.symbol, body.interval, body.start, body.end)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:
        raise HTTPException(502, f"수집 실패: {type(e).__name__}: {e}") from None


class BacktestIn(BaseModel):
    strategy: str = "bb_ema_volume"
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    params: dict = Field(default_factory=dict)
    risk: dict | None = None  # 없으면 현재 리스크 설정 버전 사용
    cost: CostModel = Field(default_factory=CostModel)
    initial_equity: float = Field(500.0, gt=0)
    apply_loss_limits: bool = True  # 일일 손실·누적 낙폭 잠금 적용 여부
    start: datetime | None = None
    end: datetime | None = None


@router.post("/backtests")
def create_backtest(body: BacktestIn, session: Session = Depends(get_session)):
    try:
        cls = get_strategy(body.strategy)
        strategy = cls(cls.Params(**body.params))
        risk = RiskSettings(**(body.risk or current_version(session).values))
    except (KeyError, ValidationError) as e:
        raise HTTPException(422, str(e)) from None
    try:
        df = market.load_dataset(body.symbol, body.interval)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    if body.start is not None:
        df = df[df["open_time"] >= body.start]
    if body.end is not None:
        df = df[df["open_time"] <= body.end]
    if len(df) <= strategy.warmup_bars():
        raise HTTPException(400, f"봉 수 부족: {len(df)} (준비 봉 {strategy.warmup_bars()} 필요)")

    result = run_backtest(
        df, strategy, risk, body.cost, body.initial_equity, body.apply_loss_limits
    )
    out = result.to_dict()
    run = BacktestRun(
        strategy=cls.name,
        strategy_version=cls.version,
        symbol=body.symbol.upper(),
        interval=body.interval,
        request={
            **body.model_dump(mode="json"),
            "params": strategy.params.model_dump(),
            "risk": risk.model_dump(),
            "bars": len(df),
        },
        metrics=out["metrics"],
        result=out,
    )
    session.add(run)
    session.commit()
    return {"id": run.id, **out}


@router.get("/backtests")
def list_backtests(session: Session = Depends(get_session)):
    rows = session.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(100)).all()
    return [
        {
            "id": r.id,
            "strategy": r.strategy,
            "strategy_version": r.strategy_version,
            "symbol": r.symbol,
            "interval": r.interval,
            "metrics": r.metrics,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/backtests/{run_id}")
def get_backtest(run_id: int, session: Session = Depends(get_session)):
    r = session.get(BacktestRun, run_id)
    if r is None:
        raise HTTPException(404, "백테스트 없음")
    return {"id": r.id, "request": r.request, **r.result}
