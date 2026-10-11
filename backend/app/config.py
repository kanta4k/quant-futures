from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # 1단계(로컬 PC)는 SQLite, 서버 이전 시 PostgreSQL URL로 교체 (PRD FR-17)
    database_url: str = f"sqlite:///{BACKEND_DIR / 'var' / 'quant.db'}"
    data_dir: Path = BACKEND_DIR / "var" / "market"

    # 위험 증가 변경 시 1회 확인용 로컬 비밀번호 (PRD FR-08 간편 변경 UX)
    dashboard_password: str = ""

    # API 키는 OS 키체인에 저장한다 (PRD A-18, A-19)
    keyring_service: str = "quant-futures"

    binance_futures_url: str = "https://fapi.binance.com"
    binance_testnet_url: str = "https://testnet.binancefuture.com"


settings = Settings()
