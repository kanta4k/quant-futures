from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import backtest, exchange, risk
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Quant Futures API", version="0.1.0", lifespan=lifespan)
app.include_router(risk.router)
app.include_router(backtest.router)
app.include_router(exchange.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "BACKTEST",  # 페이퍼·실거래 엔진은 이후 마일스톤 (PRD 10장)
        "location": "LOCAL",
        "live_enabled": False,
        "password_configured": bool(settings.dashboard_password),
    }
