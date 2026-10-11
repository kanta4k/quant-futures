"""Binance USDⓈ-M 공개 시장데이터 수집 (API 키 불필요, PRD FR-01).

- 완성 봉만 저장한다 (현재 진행 중인 봉 제외)
- 저장 형식: Parquet, var/market/{SYMBOL}_{interval}.parquet
"""

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

from app.config import settings

INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]
EXCLUDED_BASES = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP"}


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_klines(
    symbol: str, interval: str, start: datetime, end: datetime, client: httpx.Client | None = None
) -> pd.DataFrame:
    if interval not in INTERVAL_MS:
        raise ValueError(f"지원하지 않는 interval: {interval}")
    own = client is None
    client = client or httpx.Client(base_url=settings.binance_futures_url, timeout=20)
    rows: list[list] = []
    cursor, end_ms = _ms(start), min(_ms(end), int(time.time() * 1000))
    try:
        while cursor < end_ms:
            r = client.get(
                "/fapi/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1500,
                },
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1][0] + INTERVAL_MS[interval]
            time.sleep(0.2)  # 가중치 제한 여유
    finally:
        if own:
            client.close()

    df = pd.DataFrame(rows, columns=KLINE_COLS)
    if df.empty:
        return df
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    now_ms = int(time.time() * 1000)
    df = df[df["close_time"] < now_ms]  # 미완성 봉 제외
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].reset_index(
        drop=True
    )


def fetch_funding(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    rows: list[dict] = []
    cursor, end_ms = _ms(start), _ms(end)
    with httpx.Client(base_url=settings.binance_futures_url, timeout=20) as client:
        while cursor < end_ms:
            r = client.get(
                "/fapi/v1/fundingRate",
                params={"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1]["fundingTime"] + 1
            time.sleep(0.2)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["funding_time", "funding_rate"])
    df["funding_time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df[["funding_time", "funding_rate"]]


def attach_funding(klines: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """펀딩 시각이 속한 봉에 요율을 붙인다."""
    out = klines.copy()
    out["funding_rate"] = float("nan")
    if funding.empty:
        return out
    f = funding.copy()
    f["open_time"] = f["funding_time"].dt.floor("h")
    out = out.drop(columns="funding_rate").merge(
        f[["open_time", "funding_rate"]].drop_duplicates("open_time"), on="open_time", how="left"
    )
    return out


def top_symbols_by_quote_volume(n: int = 5) -> list[dict]:
    """24h 거래대금 상위 USDT 무기한 (스테이블 기반 종목 제외).

    TODO(PRD FR-15): 완료된 7일 거래대금 기준, 신규 상장·거래 상태 필터 추가.
    """
    with httpx.Client(base_url=settings.binance_futures_url, timeout=20) as client:
        info = client.get("/fapi/v1/exchangeInfo").json()
        perps = {
            s["symbol"]
            for s in info["symbols"]
            if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("baseAsset") not in EXCLUDED_BASES
        }
        tickers = client.get("/fapi/v1/ticker/24hr").json()
    ranked = sorted(
        (t for t in tickers if t["symbol"] in perps),
        key=lambda t: float(t["quoteVolume"]),
        reverse=True,
    )
    return [
        {"symbol": t["symbol"], "quote_volume_24h": float(t["quoteVolume"])} for t in ranked[:n]
    ]


def dataset_path(symbol: str, interval: str) -> Path:
    return settings.data_dir / f"{symbol.upper()}_{interval}.parquet"


def download_dataset(symbol: str, interval: str, start: datetime, end: datetime) -> dict:
    symbol = symbol.upper()
    kl = fetch_klines(symbol, interval, start, end)
    if kl.empty:
        raise ValueError("수집된 봉이 없습니다")
    df = attach_funding(kl, fetch_funding(symbol, start, end))
    path = dataset_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return describe_dataset(path)


def load_dataset(symbol: str, interval: str) -> pd.DataFrame:
    path = dataset_path(symbol, interval)
    if not path.exists():
        raise FileNotFoundError(f"데이터셋 없음: {symbol} {interval} — 먼저 데이터를 수집하세요")
    return pd.read_parquet(path)


def describe_dataset(path: Path) -> dict:
    df = pd.read_parquet(path, columns=["open_time"])
    symbol, interval = path.stem.rsplit("_", 1)
    return {
        "symbol": symbol,
        "interval": interval,
        "bars": len(df),
        "start": df["open_time"].min().isoformat() if len(df) else None,
        "end": df["open_time"].max().isoformat() if len(df) else None,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
    }


def list_datasets() -> list[dict]:
    if not settings.data_dir.exists():
        return []
    return [describe_dataset(p) for p in sorted(settings.data_dir.glob("*.parquet"))]
