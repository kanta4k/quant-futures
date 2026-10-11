"""전략 플러그인 공통 인터페이스 (PRD FR-16).

전략은 완성 봉 데이터로 진입·청산 신호와 보호 가격 계산용 ATR만 만든다.
수량 계산, 리스크 검사, 주문 실행은 전략 바깥(백테스트 엔진 / 거래 엔진)이 담당한다.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd
from pydantic import BaseModel

# compute() 결과에 반드시 있어야 하는 열
SIGNAL_COLUMNS = ["entry_long", "entry_short", "exit_long", "exit_short", "atr"]


class StrategyParams(BaseModel):
    timeframe: str = "1h"
    stop_atr_multiple: float = 2.0
    take_profit_atr_multiple: float = 3.0
    max_holding_bars: int = 48
    cooldown_bars: int = 2


class Strategy(ABC):
    name: ClassVar[str]
    version: ClassVar[str]
    label: ClassVar[str]
    Params: ClassVar[type[StrategyParams]]

    def __init__(self, params: StrategyParams | None = None):
        self.params = params or self.Params()

    @abstractmethod
    def warmup_bars(self) -> int:
        """신호 생성 전에 필요한 준비 봉 수."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLCV(+quote_volume) 데이터프레임을 받아 SIGNAL_COLUMNS를 포함한 데이터프레임을 반환.

        t행의 신호는 t봉 마감 후 확정된 정보만 사용해야 한다 (미래 데이터 참조 금지).
        """
