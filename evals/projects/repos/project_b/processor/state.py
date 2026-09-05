from enum import Enum

class OrderState(Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PENDING: {OrderState.PAID, OrderState.CANCELLED},
    OrderState.PAID: {OrderState.PROCESSING, OrderState.REFUNDED},
    OrderState.PROCESSING: {OrderState.SHIPPED, OrderState.REFUNDED},
    OrderState.SHIPPED: {OrderState.DELIVERED},
    OrderState.DELIVERED: set(),
    OrderState.CANCELLED: set(),
    OrderState.REFUNDED: set(),
}

class InvalidStateTransitionError(Exception):
    pass

def can_transition(current: OrderState, target: OrderState) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
