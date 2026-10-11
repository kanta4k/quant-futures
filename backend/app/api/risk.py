import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.risk import (
    HARD_POLICY_VERSION,
    PRESETS,
    RiskSettings,
    classify_change,
    field_specs,
    preview,
)
from app.db import RiskSettingsVersion, audit, get_session

router = APIRouter(prefix="/api/risk", tags=["risk"])


def current_version(session: Session) -> RiskSettingsVersion:
    row = session.scalars(
        select(RiskSettingsVersion).order_by(RiskSettingsVersion.id.desc()).limit(1)
    ).first()
    if row is None:  # init_db()에서 초기 버전을 만든다
        raise HTTPException(500, "리스크 설정이 초기화되지 않았습니다")
    return row


def _parse(values: dict) -> RiskSettings:
    try:
        return RiskSettings(**values)
    except ValidationError as e:
        raise HTTPException(422, detail=[err["msg"] for err in e.errors()]) from None


def _version_out(row: RiskSettingsVersion) -> dict:
    return {
        "version": row.id,
        "values": row.values,
        "change_kind": row.change_kind,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    row = current_version(session)
    return {
        **_version_out(row),
        "fields": field_specs(),
        "hard_policy_version": HARD_POLICY_VERSION,
    }


@router.get("/presets")
def get_presets():
    return PRESETS


class PreviewIn(BaseModel):
    values: dict
    equity: float = 500.0


@router.post("/preview")
def post_preview(body: PreviewIn, session: Session = Depends(get_session)):
    new = _parse(body.values)
    old = RiskSettings(**current_version(session).values)
    kind, diffs = classify_change(old, new)
    return {
        "change_kind": kind,
        "diffs": diffs,
        "preview": preview(new, body.equity),
        "requires_password": kind in ("increase", "mixed"),
    }


class SaveIn(BaseModel):
    values: dict
    password: str | None = None
    note: str = ""


@router.put("/settings")
def put_settings(body: SaveIn, session: Session = Depends(get_session)):
    new = _parse(body.values)
    old = RiskSettings(**current_version(session).values)
    kind, diffs = classify_change(old, new)
    if kind == "none":
        return {"saved": False, "reason": "변경 사항 없음"}
    if kind in ("increase", "mixed"):
        # 위험 증가는 비밀번호 1회 확인 (PRD FR-08). 위험 축소는 확인 없이 즉시 적용.
        if not settings.dashboard_password:
            raise HTTPException(
                403, "DASHBOARD_PASSWORD가 설정되지 않아 위험 증가 변경을 저장할 수 없습니다"
            )
        if not body.password or not hmac.compare_digest(body.password, settings.dashboard_password):
            raise HTTPException(401, "비밀번호가 올바르지 않습니다")
    row = RiskSettingsVersion(values=new.model_dump(), change_kind=kind, note=body.note[:200])
    session.add(row)
    session.flush()
    audit(session, "risk.update", {"version": row.id, "kind": kind, "diffs": diffs})
    session.commit()
    # 거래 엔진이 붙으면: 위험 증가분은 다음 신규 주문부터, 레버리지는 무포지션 종목부터 반영
    return {"saved": True, **_version_out(row)}


@router.get("/history")
def get_history(session: Session = Depends(get_session)):
    rows = session.scalars(
        select(RiskSettingsVersion).order_by(RiskSettingsVersion.id.desc()).limit(50)
    ).all()
    return [_version_out(r) for r in rows]


class RollbackIn(BaseModel):
    password: str | None = None


@router.post("/rollback/{version}")
def rollback(version: int, body: RollbackIn, session: Session = Depends(get_session)):
    target = session.get(RiskSettingsVersion, version)
    if target is None:
        raise HTTPException(404, "버전 없음")
    return put_settings(
        SaveIn(values=target.values, password=body.password, note=f"v{version}로 되돌림"), session
    )
