"""리스크 설정 — PRD FR-08 (설정표, 하드 상한, 프리셋, 위험 증가/축소 판정).

하드 상한(RISK_FIELDS의 lo/hi)은 대시보드에서 바꿀 수 없고 코드 버전으로만 변경한다.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, model_validator

HARD_POLICY_VERSION = "2026.10-1"


@dataclass(frozen=True)
class RiskField:
    label: str
    unit: str
    default: float
    lo: float
    hi: float
    # +1: 값이 커질수록 위험 증가, -1: 값이 작아질수록 위험 증가
    risk_direction: int
    step: float


RISK_FIELDS: dict[str, RiskField] = {
    "capital_usage_pct": RiskField("자본 사용률", "%", 100, 10, 100, +1, 5),
    "leverage": RiskField("레버리지", "x", 2, 1, 5, +1, 1),
    "risk_per_trade_pct": RiskField("주문별 계획 손실", "%", 0.25, 0.01, 0.5, +1, 0.01),
    "total_risk_pct": RiskField("전체 계획 손실 합계", "%", 0.5, 0.01, 1.0, +1, 0.01),
    "daily_loss_pct": RiskField("일일 손실 한도", "%", 2, 0.1, 3, +1, 0.1),
    "max_drawdown_pct": RiskField("누적 낙폭 한도", "%", 5, 0.5, 10, +1, 0.5),
    "max_positions": RiskField("최대 동시 포지션", "개", 2, 1, 5, +1, 1),
    "gross_exposure_x": RiskField("총 명목 익스포저", "x", 2.0, 0.1, 3.0, +1, 0.1),
    "symbol_exposure_x": RiskField("단일 종목 익스포저", "x", 0.75, 0.05, 1.0, +1, 0.05),
    "net_exposure_x": RiskField("절대 순 익스포저", "x", 1.0, 0.1, 2.0, +1, 0.1),
    "corr_group_exposure_x": RiskField("상관 그룹 익스포저", "x", 1.0, 0.1, 1.5, +1, 0.1),
    "corr_group_risk_pct": RiskField("상관 그룹 계획 손실", "%", 0.35, 0.01, 0.5, +1, 0.01),
    "min_free_margin_pct": RiskField("가용 증거금 최소", "%", 50, 30, 100, -1, 5),
}

MarginMode = Literal["isolated", "cross"]


class RiskSettings(BaseModel):
    capital_usage_pct: float = RISK_FIELDS["capital_usage_pct"].default
    leverage: int = int(RISK_FIELDS["leverage"].default)
    margin_mode: MarginMode = "isolated"
    risk_per_trade_pct: float = RISK_FIELDS["risk_per_trade_pct"].default
    total_risk_pct: float = RISK_FIELDS["total_risk_pct"].default
    daily_loss_pct: float = RISK_FIELDS["daily_loss_pct"].default
    max_drawdown_pct: float = RISK_FIELDS["max_drawdown_pct"].default
    max_positions: int = int(RISK_FIELDS["max_positions"].default)
    gross_exposure_x: float = RISK_FIELDS["gross_exposure_x"].default
    symbol_exposure_x: float = RISK_FIELDS["symbol_exposure_x"].default
    net_exposure_x: float = RISK_FIELDS["net_exposure_x"].default
    corr_group_exposure_x: float = RISK_FIELDS["corr_group_exposure_x"].default
    corr_group_risk_pct: float = RISK_FIELDS["corr_group_risk_pct"].default
    min_free_margin_pct: float = RISK_FIELDS["min_free_margin_pct"].default

    @model_validator(mode="after")
    def _check(self) -> "RiskSettings":
        errors = []
        for name, f in RISK_FIELDS.items():
            v = getattr(self, name)
            if not (f.lo <= v <= f.hi):
                errors.append(f"{f.label}: {v}{f.unit} — 허용 범위 {f.lo}~{f.hi}{f.unit}")
        if self.daily_loss_pct > self.max_drawdown_pct:
            errors.append("일일 손실 한도는 누적 낙폭 한도 이하여야 합니다")
        if self.risk_per_trade_pct > self.total_risk_pct:
            errors.append("주문별 계획 손실은 전체 계획 손실 합계 이하여야 합니다")
        if self.risk_per_trade_pct > self.corr_group_risk_pct:
            errors.append("주문별 계획 손실은 상관 그룹 계획 손실 이하여야 합니다")
        if self.symbol_exposure_x > self.gross_exposure_x:
            errors.append("단일 종목 익스포저는 총 명목 익스포저 이하여야 합니다")
        if self.margin_mode == "cross":
            errors.append("교차마진은 M0 검증 후 허용됩니다")
        if errors:
            raise ValueError("; ".join(errors))
        return self


PRESETS: dict[str, dict] = {
    "conservative": {"label": "보수 (기본값)", "values": RiskSettings().model_dump()},
    "neutral": {
        "label": "중립",
        "values": RiskSettings(
            leverage=3,
            risk_per_trade_pct=0.35,
            total_risk_pct=0.7,
            daily_loss_pct=2.5,
            max_drawdown_pct=7,
            max_positions=3,
            gross_exposure_x=2.5,
            symbol_exposure_x=0.9,
            corr_group_risk_pct=0.45,
            min_free_margin_pct=40,
        ).model_dump(),
    },
    "aggressive": {
        "label": "적극",
        "values": RiskSettings(
            leverage=5,
            risk_per_trade_pct=0.5,
            total_risk_pct=1.0,
            daily_loss_pct=3,
            max_drawdown_pct=10,
            max_positions=5,
            gross_exposure_x=3.0,
            symbol_exposure_x=1.0,
            net_exposure_x=2.0,
            corr_group_exposure_x=1.5,
            corr_group_risk_pct=0.5,
            min_free_margin_pct=30,
        ).model_dump(),
    },
}


ChangeKind = Literal["none", "decrease", "increase", "mixed"]


def classify_change(old: RiskSettings, new: RiskSettings) -> tuple[ChangeKind, list[dict]]:
    """변경 항목별 위험 방향을 판정한다. 위험 증가가 하나라도 있으면 비밀번호 확인 대상."""
    diffs = []
    up = down = False
    for name, f in RISK_FIELDS.items():
        a, b = getattr(old, name), getattr(new, name)
        if a == b:
            continue
        increases = (b - a) * f.risk_direction > 0
        up |= increases
        down |= not increases
        diffs.append(
            {"field": name, "label": f.label, "old": a, "new": b, "increases_risk": increases}
        )
    if old.margin_mode != new.margin_mode:
        up = True
        diffs.append(
            {
                "field": "margin_mode",
                "label": "마진 모드",
                "old": old.margin_mode,
                "new": new.margin_mode,
                "increases_risk": True,
            }
        )
    kind: ChangeKind = (
        "mixed" if up and down else "increase" if up else "decrease" if down else "none"
    )
    return kind, diffs


def preview(values: RiskSettings, equity: float) -> dict:
    """저장 전 미리보기 — USDT 금액 기준 (PRD FR-08 즉시 미리보기)."""
    e_bot = equity * values.capital_usage_pct / 100
    return {
        "equity": equity,
        "bot_capital": e_bot,
        "max_loss_per_trade": e_bot * values.risk_per_trade_pct / 100,
        "max_total_open_risk": e_bot * values.total_risk_pct / 100,
        "daily_loss_limit": e_bot * values.daily_loss_pct / 100,
        "drawdown_limit": e_bot * values.max_drawdown_pct / 100,
        "max_symbol_notional": e_bot * values.symbol_exposure_x,
        "max_gross_notional": e_bot * values.gross_exposure_x,
    }


def field_specs() -> list[dict]:
    return [
        {
            "field": k,
            "label": f.label,
            "unit": f.unit,
            "default": f.default,
            "min": f.lo,
            "max": f.hi,
            "step": f.step,
            "risk_direction": f.risk_direction,
        }
        for k, f in RISK_FIELDS.items()
    ]
