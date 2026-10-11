"""시간순 구간 분리 (PRD FR-03, A-13).

학습(train) → 검증(validation) → 최종 평가(test) 순서로 겹치지 않게 나눈다.
최종 평가 구간은 파라미터 선택에 쓰지 않는다 — 탐색(optimize)은 train/validation만 본다.
"""

import pandas as pd
from pydantic import BaseModel, Field, model_validator

SEGMENTS = ("train", "validation", "test")


class SplitSpec(BaseModel):
    train: float = Field(0.6, gt=0, lt=1)
    validation: float = Field(0.2, ge=0, lt=1)
    test: float = Field(0.2, ge=0, lt=1)

    @model_validator(mode="after")
    def _sum_to_one(self):
        if abs(self.train + self.validation + self.test - 1) > 1e-6:
            raise ValueError("train + validation + test 비율의 합은 1이어야 합니다")
        return self


def split_bounds(
    start: pd.Timestamp, end: pd.Timestamp, spec: SplitSpec
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """[start, end) 기간을 비율대로 나눠 일 단위로 맞춘 경계를 반환한다."""
    span = end - start
    b1 = (start + span * spec.train).ceil("D")
    b2 = (start + span * (spec.train + spec.validation)).ceil("D")
    bounds = {"train": (start, b1), "validation": (b1, b2), "test": (b2, end)}
    return {k: v for k, v in bounds.items() if v[0] < v[1]}
