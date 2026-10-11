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


def test_backtest_api(synthetic_ohlcv):
    from app.data.binance_public import dataset_path

    path = dataset_path("TESTUSDT", "1h")
    path.parent.mkdir(parents=True, exist_ok=True)
    synthetic_ohlcv.to_parquet(path, index=False)
    with TestClient(app) as c:
        assert any(d["symbol"] == "TESTUSDT" for d in c.get("/api/data/datasets").json())
        r = c.post(
            "/api/backtests",
            json={
                "symbol": "TESTUSDT",
                "params": {"ema_fast_period": 20, "ema_slow_period": 60, "warmup_multiplier": 3},
            },
        )
        assert r.status_code == 200, r.text
        run_id = r.json()["id"]
        assert c.get(f"/api/backtests/{run_id}").json()["metrics"]["trades"] > 0
