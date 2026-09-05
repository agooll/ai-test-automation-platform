from typing import Optional

class InventoryManager:
    def __init__(self):
        self._items: dict[str, dict] = {}

    def add_item(self, sku: str, name: str, price: float, quantity: int) -> dict:
        if not sku or not sku.isalnum():
            raise ValueError("SKU must be alphanumeric and non-empty")
        if not name or len(name.strip()) == 0:
            raise ValueError("Item name cannot be empty")
        if price <= 0:
            raise ValueError("Price must be positive")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if sku in self._items:
            raise ValueError(f"SKU '{sku}' already exists")

        item = {
            "sku": sku,
            "name": name.strip(),
            "price": float(price),
            "quantity": int(quantity),
        }
        self._items[sku] = item
        return item

    def get_item(self, sku: str) -> Optional[dict]:
        return self._items.get(sku)

    def deduct_stock(self, sku: str, amount: int) -> dict:
        if amount <= 0:
            raise ValueError("Deduct amount must be positive")
        item = self._items.get(sku)
        if not item:
            raise KeyError(f"Item '{sku}' not found")
        if item["quantity"] < amount:
            raise ValueError(f"Insufficient stock for SKU '{sku}': available {item['quantity']}, requested {amount}")
        item["quantity"] -= amount
        return item

    def restock(self, sku: str, amount: int) -> dict:
        if amount <= 0:
            raise ValueError("Restock amount must be positive")
        item = self._items.get(sku)
        if not item:
            raise KeyError(f"Item '{sku}' not found")
        item["quantity"] += amount
        return item
