from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.risk import current_version
from app.backtest import service
from app.backtest.service import BacktestRequest, OptimizeRequest, Prepared
from app.data import binance_public as market
from app.db import BacktestRun, get_session
from app.strategies import REGISTRY

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


def _prepare(req: BacktestRequest, session: Session) -> Prepared:
    try:
        return Prepared(req, current_version(session).values)
    except (KeyError, ValidationError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.post("/backtests")
def create_backtest(body: BacktestRequest, session: Session = Depends(get_session)):
    prep = _prepare(body, session)
    try:
        out = service.run_request(prep)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    run = BacktestRun(
        strategy=prep.strategy_cls.name,
        strategy_version=prep.strategy_cls.version,
        symbol=",".join(body.symbols),
        interval=body.interval,
        request={
            **body.model_dump(mode="json"),
            "params": prep.strategy.params.model_dump(),
            "risk": prep.risk.model_dump(),
        },
        metrics={
            **out["metrics"],
            "segments": {k: v["metrics"] for k, v in out["segments"].items()},
        },
        result=out,
    )
    session.add(run)
    session.commit()
    return {"id": run.id, "request": run.request, **out}


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
    return {"id": r.id, "request": r.request, "segments": {}, **r.result}


@router.post("/optimize")
def start_optimize(body: OptimizeRequest, session: Session = Depends(get_session)):
    try:
        job = service.start_optimize(body, current_version(session).values)
    except (KeyError, ValidationError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    return job.view(body.objective, body.min_trades)


@router.get("/optimize/{job_id}")
def get_optimize(job_id: str):
    if job_id not in service.JOBS:
        raise HTTPException(404, "탐색 작업 없음 (서버 재시작 시 사라집니다)")
    job, req = service.JOBS[job_id]
    return job.view(req.objective, req.min_trades)
