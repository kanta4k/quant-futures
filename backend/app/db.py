from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RiskSettingsVersion(Base):
    """리스크 설정 버전 (PRD FR-08, FR-14). 행은 수정하지 않고 새 버전을 추가한다."""

    __tablename__ = "risk_settings_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    values: Mapped[dict] = mapped_column(JSON)
    change_kind: Mapped[str] = mapped_column(String(16))  # initial / decrease / increase / mixed
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    request: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str):
    if url.startswith("sqlite:///"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    # 리스크 설정 초기 버전은 기동 시 한 번만 만든다 (동시 요청에서 중복 생성 방지)
    from app.core.risk import RiskSettings

    with SessionLocal() as session:
        if session.query(RiskSettingsVersion).first() is None:
            session.add(
                RiskSettingsVersion(
                    values=RiskSettings().model_dump(), change_kind="initial", note="기본값"
                )
            )
            session.commit()


def get_session():
    with SessionLocal() as session:
        yield session


def audit(session: Session, action: str, detail: dict | None = None) -> None:
    session.add(AuditEvent(action=action, detail=detail or {}))
