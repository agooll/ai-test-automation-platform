import uuid
from typing import Optional
from processor.discount import DiscountCalculator
from processor.state import InvalidStateTransitionError, OrderState, can_transition

class Order:
    def __init__(self, customer_id: str, is_vip: bool = False):
        self.order_id = str(uuid.uuid4())
        self.customer_id = customer_id
        self.is_vip = is_vip
        self.state = OrderState.PENDING
        self.items: list[dict] = []
        self.coupon_code: Optional[str] = None
        self.subtotal: float = 0.0
        self.discount: float = 0.0
        self.total: float = 0.0

    def add_item(self, item_id: str, price: float, quantity: int = 1) -> None:
        if self.state != OrderState.PENDING:
            raise InvalidStateTransitionError("Cannot modify items after order is placed")
        if price <= 0:
            raise ValueError("Price must be positive")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        self.items.append({"item_id": item_id, "price": price, "quantity": quantity})
        self._recalculate()

    def apply_coupon(self, code: str) -> None:
        if self.state != OrderState.PENDING:
            raise InvalidStateTransitionError("Cannot apply coupon to non-pending order")
        self.coupon_code = code
        self._recalculate()

    def _recalculate(self) -> None:
        self.subtotal = sum(it["price"] * it["quantity"] for it in self.items)
        self.discount = DiscountCalculator.calculate_discount(self.subtotal, self.coupon_code, self.is_vip)
        self.total = max(0.0, self.subtotal - self.discount)

    def transition_to(self, new_state: OrderState) -> None:
        if not can_transition(self.state, new_state):
            raise InvalidStateTransitionError(f"Cannot transition order {self.order_id} from {self.state.value} to {new_state.value}")
        self.state = new_state
