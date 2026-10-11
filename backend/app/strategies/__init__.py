from app.strategies.base import Strategy
from app.strategies.bb_ema_volume import BbEmaVolume

# 새 전략은 Strategy를 상속해 여기에 등록한다 (PRD FR-16)
REGISTRY: dict[str, type[Strategy]] = {
    BbEmaVolume.name: BbEmaVolume,
}


def get_strategy(name: str) -> type[Strategy]:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"알 수 없는 전략: {name}") from None
