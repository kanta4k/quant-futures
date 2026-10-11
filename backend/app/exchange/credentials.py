"""Binance API 키 저장 — OS 키체인 사용, 평문 파일·DB·응답에 노출하지 않는다 (PRD A-19).

계정 연동(실거래 엔진)은 백테스트 이후 단계. 지금은 키 입력·저장·연결 테스트까지만 제공한다.
"""

import contextlib
import hashlib
import hmac
import time
from typing import Literal
from urllib.parse import urlencode

import httpx
import keyring
from keyring.errors import KeyringError

from app.config import settings

Env = Literal["testnet", "mainnet"]


def _user(env: Env, kind: str) -> str:
    return f"binance-{env}-{kind}"


def save_credentials(env: Env, api_key: str, api_secret: str) -> None:
    keyring.set_password(settings.keyring_service, _user(env, "key"), api_key)
    keyring.set_password(settings.keyring_service, _user(env, "secret"), api_secret)


def load_credentials(env: Env) -> tuple[str, str] | None:
    try:
        key = keyring.get_password(settings.keyring_service, _user(env, "key"))
        secret = keyring.get_password(settings.keyring_service, _user(env, "secret"))
    except KeyringError:
        return None
    return (key, secret) if key and secret else None


def delete_credentials(env: Env) -> None:
    for kind in ("key", "secret"):
        with contextlib.suppress(KeyringError):
            keyring.delete_password(settings.keyring_service, _user(env, kind))


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "****"


def status(env: Env) -> dict:
    creds = load_credentials(env)
    return {
        "env": env,
        "configured": creds is not None,
        "api_key_masked": mask(creds[0]) if creds else None,
    }


def test_connection(env: Env) -> dict:
    """서명된 읽기 전용 호출(/fapi/v2/account)로 키 유효성·권한을 확인한다. 주문은 보내지 않는다."""
    creds = load_credentials(env)
    if creds is None:
        return {"ok": False, "error": "저장된 API 키가 없습니다"}
    key, secret = creds
    base = settings.binance_testnet_url if env == "testnet" else settings.binance_futures_url
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    query = urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    try:
        r = httpx.get(
            f"{base}/fapi/v2/account?{query}&signature={sig}",
            headers={"X-MBX-APIKEY": key},
            timeout=10,
        )
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"연결 실패: {type(e).__name__}"}
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return {"ok": False, "error": body.get("msg", f"HTTP {r.status_code}")}
    data = r.json()
    return {
        "ok": True,
        "can_trade": data.get("canTrade"),
        "total_wallet_balance": data.get("totalWalletBalance"),
        "available_balance": data.get("availableBalance"),
    }
