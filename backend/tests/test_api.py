from fastapi.testclient import TestClient

from app.main import app


def test_risk_flow():
    with TestClient(app) as c:
        s = c.get("/api/risk/settings").json()
        assert s["values"]["leverage"] == 2
        dec = {**s["values"], "leverage": 1}
        assert c.put("/api/risk/settings", json={"values": dec}).json()["saved"]
        inc = {**dec, "leverage": 3}
        assert c.put("/api/risk/settings", json={"values": inc}).status_code == 401
        r = c.put("/api/risk/settings", json={"values": inc, "password": "test-pass"})
        assert r.json()["change_kind"] == "increase"
        bad = {**inc, "leverage": 20}
        assert c.post("/api/risk/preview", json={"values": bad}).status_code == 422


PARAMS = {"ema_fast_period": 20, "ema_slow_period": 60, "warmup_multiplier": 3}


def _write(df, symbol):
    from app.data.binance_public import dataset_path

    path = dataset_path(symbol, "1h")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_backtest_api(synthetic_ohlcv):
    _write(synthetic_ohlcv, "TESTUSDT")
    with TestClient(app) as c:
        assert any(d["symbol"] == "TESTUSDT" for d in c.get("/api/data/datasets").json())
        r = c.post("/api/backtests", json={"symbol": "TESTUSDT", "params": PARAMS})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["segments"]) == {"train", "validation", "test"}
        assert c.get(f"/api/backtests/{body['id']}").json()["metrics"]["trades"] > 0

        # 2종목 포트폴리오 + 동적 유니버스
        _write(synthetic_ohlcv.assign(close=synthetic_ohlcv["close"] * 1.01), "TEST2USDT")
        r = c.post(
            "/api/backtests",
            json={
                "symbols": ["TESTUSDT", "TEST2USDT"],
                "params": PARAMS,
                "universe": {"mode": "dynamic", "top_k": 1},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["metrics"]["trades"] > 0


def test_optimize_job(synthetic_ohlcv):
    import time

    _write(synthetic_ohlcv, "TESTUSDT")
    base = {"symbols": ["TESTUSDT"], "params": PARAMS}
    with TestClient(app) as c:
        r = c.post(
            "/api/optimize",
            json={
                "base": base,
                "grid": {"bb_stddev": [1.5, 2.0], "volume_multiplier": [1.0, 1.5]},
                "min_trades": 0,
            },
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]
        for _ in range(200):
            job = c.get(f"/api/optimize/{job_id}").json()
            if job["status"] != "running":
                break
            time.sleep(0.1)
        assert job["status"] == "done", job
        assert len(job["ranked"]) == 4
        assert "test" not in job["ranked"][0]  # 최종 평가 구간은 탐색에 사용하지 않음
        too_many = {k: list(range(20)) for k in ("bb_period", "atr_period")}
        assert c.post("/api/optimize", json={"base": base, "grid": too_many}).status_code == 422
