from typing import Any
from app.auth import UserManager
from app.inventory import InventoryManager

class AppService:
    def __init__(self):
        self.users = UserManager()
        self.inventory = InventoryManager()

    def handle_request(self, method: str, endpoint: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        if endpoint == "/auth/register" and method == "POST":
            user = self.users.register(payload.get("username", ""), payload.get("email", ""), payload.get("password", ""))
            return {"status": 201, "data": user}

        if endpoint == "/auth/login" and method == "POST":
            tok = self.users.login(payload.get("username", ""), payload.get("password", ""))
            return {"status": 200, "data": {"token": tok}}

        # Protected endpoints
        current_user = self.users.authenticate(token or "")
        if not current_user:
            return {"status": 401, "error": "Unauthorized"}

        if endpoint == "/inventory/items" and method == "POST":
            item = self.inventory.add_item(
                payload.get("sku", ""),
                payload.get("name", ""),
                payload.get("price", 0.0),
                payload.get("quantity", 0),
            )
            return {"status": 201, "data": item}

        if endpoint == "/inventory/deduct" and method == "POST":
            item = self.inventory.deduct_stock(payload.get("sku", ""), payload.get("amount", 0))
            return {"status": 200, "data": item}

        if endpoint == "/inventory/restock" and method == "POST":
            item = self.inventory.restock(payload.get("sku", ""), payload.get("amount", 0))
            return {"status": 200, "data": item}

        return {"status": 404, "error": "Endpoint not found"}
