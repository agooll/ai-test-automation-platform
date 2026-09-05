"""Script to generate the 24 benchmark cases, requirements, mutants, and suites."""

import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"

REQ_DIR = EVALS_DIR / "requirements"
MUT_DIR = EVALS_DIR / "mutants"
CASE_DIR = EVALS_DIR / "cases"
SUITE_DIR = EVALS_DIR / "suites"

for d in [REQ_DIR, MUT_DIR, CASE_DIR, SUITE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 24 Cases specification
CASES = [
    # 1. happy_path (4)
    {
        "id": "case_01",
        "project": "project_a",
        "category": "happy_path",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: User Registration
The `UserManager.register(username, email, password)` method must successfully register a new user when provided with valid parameters:
- `username`: string with at least 3 characters
- `email`: valid email string (e.g. user@example.com)
- `password`: string with at least 8 characters

The method must return a dictionary containing `{"username": username, "email": email, "role": "user"}`.
""",
        "mutant_desc": "Registration assigns role 'guest' instead of 'user'",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -32,3 +32,3 @@
-        return {"username": username, "email": email, "role": "user"}
+        return {"username": username, "email": email, "role": "guest"}
""",
    },
    {
        "id": "case_02",
        "project": "project_b",
        "category": "happy_path",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "processor.order.Order.add_item",
        "req_text": """# Requirement: Order Item Addition and Subtotal
The `Order` class allows adding items to a pending order via `add_item(item_id, price, quantity=1)`.
When items are added:
- `subtotal` must equal the sum of `price * quantity` for all items in the order.
- In the absence of discounts or coupons, `total` must equal `subtotal`.
""",
        "mutant_desc": "Subtotal calculation adds fixed surcharge of 10.0",
        "mutant_patch": """--- a/processor/order.py
+++ b/processor/order.py
@@ -31,3 +31,3 @@
-        self.subtotal = sum(it["price"] * it["quantity"] for it in self.items)
+        self.subtotal = sum(it["price"] * it["quantity"] for it in self.items) + 10.0
""",
    },
    {
        "id": "case_03",
        "project": "project_a",
        "category": "happy_path",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "app.inventory.InventoryManager.add_item",
        "req_text": """# Requirement: Inventory Item Addition
The `InventoryManager.add_item(sku, name, price, quantity)` method adds an item to inventory:
- `sku` must be an alphanumeric identifier.
- `name` must be a non-empty string.
- `price` must be a positive float.
- `quantity` must be non-negative integer.

It must return the added item dict with fields `sku`, `name`, `price`, `quantity`.
""",
        "mutant_desc": "add_item forces quantity to 0 regardless of input",
        "mutant_patch": """--- a/app/inventory.py
+++ b/app/inventory.py
@@ -23,3 +23,3 @@
-            "quantity": int(quantity),
+            "quantity": 0,
""",
    },
    {
        "id": "case_04",
        "project": "project_b",
        "category": "happy_path",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "processor.discount.DiscountCalculator.calculate_discount",
        "req_text": """# Requirement: Combined VIP and Coupon Discount Calculation
The `DiscountCalculator.calculate_discount(total_amount, coupon_code, is_vip)` calculates combined discounts:
- If `is_vip` is True, a 10% discount rate applies.
- If `coupon_code` is 'SAVE10', an additional 10% rate applies (total 20% rate).
- If `coupon_code` is 'FLAT20', 20.0 fixed deduction is added to the percentage discount.
The returned discount must accurately combine both rates and fixed deductions.
""",
        "mutant_desc": "VIP discount rate reduced to 5% instead of 10%",
        "mutant_patch": """--- a/processor/discount.py
+++ b/processor/discount.py
@@ -12,3 +12,3 @@
-            rate += 0.10  # 10% VIP discount
+            rate += 0.05  # 5% VIP discount
""",
    },

    # 2. boundary_value (4)
    {
        "id": "case_05",
        "project": "project_a",
        "category": "boundary_value",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: Boundary Username and Password Lengths
The `UserManager.register` method enforces minimum length bounds:
- Exactly 3 characters for `username` must be accepted.
- Exactly 2 characters for `username` must raise `ValueError`.
- Exactly 8 characters for `password` must be accepted.
- Exactly 7 characters for `password` must raise `ValueError`.
""",
        "mutant_desc": "Requires username length >= 5 instead of 3",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -12,3 +12,3 @@
-        if not username or len(username) < 3:
+        if not username or len(username) < 5:
""",
    },
    {
        "id": "case_06",
        "project": "project_b",
        "category": "boundary_value",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "processor.discount.DiscountCalculator.calculate_discount",
        "req_text": """# Requirement: Discount Ceiling Boundary
The discount calculated by `DiscountCalculator.calculate_discount` must never exceed `total_amount`.
For example, with `total_amount = 15.0` and coupon `'FLAT20'`, the discount must be capped at `15.0`, not `20.0`.
""",
        "mutant_desc": "Omits discount ceiling cap against total_amount",
        "mutant_patch": """--- a/processor/discount.py
+++ b/processor/discount.py
@@ -27,3 +27,3 @@
-        return min(discount, total_amount)
+        return discount
""",
    },
    {
        "id": "case_07",
        "project": "project_a",
        "category": "boundary_value",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "app.inventory.InventoryManager.deduct_stock",
        "req_text": """# Requirement: Exact Stock Depletion to Zero
The `InventoryManager.deduct_stock(sku, amount)` method must allow deducting the exact available quantity, reducing `quantity` to 0.
Subsequent deduction when `quantity == 0` must raise `ValueError`.
""",
        "mutant_desc": "Disallows deducting exact available stock by using <= instead of <",
        "mutant_patch": """--- a/app/inventory.py
+++ b/app/inventory.py
@@ -33,3 +33,3 @@
-        if item["quantity"] < amount:
+        if item["quantity"] <= amount:
""",
    },
    {
        "id": "case_08",
        "project": "project_b",
        "category": "boundary_value",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "processor.discount.DiscountCalculator.calculate_discount",
        "req_text": """# Requirement: Zero Subtotal Boundary Discount
When `total_amount == 0.0`, `DiscountCalculator.calculate_discount` must return `0.0` regardless of coupons or VIP status, and must not produce negative values.
""",
        "mutant_desc": "Applies fixed deduction even when total_amount is zero",
        "mutant_patch": """--- a/processor/discount.py
+++ b/processor/discount.py
@@ -8,4 +8,2 @@
-        if total_amount == 0:
-            return 0.0
""",
    },

    # 3. error_handling (4)
    {
        "id": "case_09",
        "project": "project_a",
        "category": "error_handling",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: Email Format Validation Error
The `UserManager.register` method must validate that `email` matches a standard email pattern (e.g. contains '@' and domain).
If the email format is invalid (e.g. 'plainstring', 'missing@domain'), it must raise `ValueError("Invalid email format")`.
""",
        "mutant_desc": "Bypasses email regex validation",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -14,4 +14,2 @@
-        if not EMAIL_REGEX.match(email):
-            raise ValueError("Invalid email format")
""",
    },
    {
        "id": "case_10",
        "project": "project_b",
        "category": "error_handling",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "processor.order.Order.add_item",
        "req_text": """# Requirement: Non-Positive Price and Quantity Error Handling
The `Order.add_item` method must reject non-positive prices and quantities:
- `price <= 0` must raise `ValueError("Price must be positive")`.
- `quantity <= 0` must raise `ValueError("Quantity must be positive")`.
""",
        "mutant_desc": "Allows zero or negative price without raising ValueError",
        "mutant_patch": """--- a/processor/order.py
+++ b/processor/order.py
@@ -23,4 +23,2 @@
-        if price <= 0:
-            raise ValueError("Price must be positive")
""",
    },
    {
        "id": "case_11",
        "project": "project_a",
        "category": "error_handling",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "app.inventory.InventoryManager.deduct_stock",
        "req_text": """# Requirement: Insufficient Stock Error
When `deduct_stock` is called with an `amount` greater than the currently available stock, it must raise a `ValueError` indicating insufficient stock and preserve original stock.
""",
        "mutant_desc": "Allows stock deduction below zero without raising error",
        "mutant_patch": """--- a/app/inventory.py
+++ b/app/inventory.py
@@ -33,4 +33,2 @@
-        if item["quantity"] < amount:
-            raise ValueError(f"Insufficient stock for SKU '{sku}': available {item['quantity']}, requested {amount}")
""",
    },
    {
        "id": "case_12",
        "project": "project_b",
        "category": "error_handling",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "processor.discount.DiscountCalculator.calculate_discount",
        "req_text": """# Requirement: Invalid Coupon Code Error Handling
When an unrecognized `coupon_code` (e.g. 'INVALID_CODE', 'BOGUS') is passed to `DiscountCalculator.calculate_discount`, it must raise `ValueError("Unknown coupon code...")`.
""",
        "mutant_desc": "Silently ignores unknown coupon codes instead of raising ValueError",
        "mutant_patch": """--- a/processor/discount.py
+++ b/processor/discount.py
@@ -23,4 +23,2 @@
-            else:
-                raise ValueError(f"Unknown coupon code '{coupon_code}'")
""",
    },

    # 4. concurrency_state (4)
    {
        "id": "case_13",
        "project": "project_b",
        "category": "concurrency_state",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "processor.state.can_transition",
        "req_text": """# Requirement: Valid Order State Transitions
The `can_transition(current_state, new_state)` helper and `Order.transition_to(new_state)` must permit valid lifecycle transitions:
- `OrderState.PENDING` -> `OrderState.PAID`
- `OrderState.PENDING` -> `OrderState.CANCELLED`
""",
        "mutant_desc": "Disallows transition from PENDING to PAID",
        "mutant_patch": """--- a/processor/state.py
+++ b/processor/state.py
@@ -13,3 +13,3 @@
-    OrderState.PENDING: {OrderState.PAID, OrderState.CANCELLED},
+    OrderState.PENDING: {OrderState.CANCELLED},
""",
    },
    {
        "id": "case_14",
        "project": "project_b",
        "category": "concurrency_state",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "processor.order.Order.transition_to",
        "req_text": """# Requirement: Invalid State Transition Rejection
Attempting an invalid state transition (e.g. `DELIVERED` -> `CANCELLED`, or `PAID` -> `PENDING`) must raise `InvalidStateTransitionError`.
""",
        "mutant_desc": "Erroneously allows transition from DELIVERED to CANCELLED",
        "mutant_patch": """--- a/processor/state.py
+++ b/processor/state.py
@@ -17,3 +17,3 @@
-    OrderState.DELIVERED: set(),
+    OrderState.DELIVERED: {OrderState.CANCELLED},
""",
    },
    {
        "id": "case_15",
        "project": "project_b",
        "category": "concurrency_state",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "processor.order.Order.add_item",
        "req_text": """# Requirement: State Guard on Order Item Modification
Once an order has transitioned past `OrderState.PENDING` (for example to `OrderState.PAID`), calls to `add_item` or `apply_coupon` must be rejected with `InvalidStateTransitionError`.
""",
        "mutant_desc": "Omits state check in add_item allowing mutation after payment",
        "mutant_patch": """--- a/processor/order.py
+++ b/processor/order.py
@@ -21,4 +21,2 @@
-        if self.state != OrderState.PENDING:
-            raise InvalidStateTransitionError("Cannot modify items after order is placed")
""",
    },
    {
        "id": "case_16",
        "project": "project_b",
        "category": "concurrency_state",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "processor.state.can_transition",
        "req_text": """# Requirement: Terminal State Immutability
Terminal order states `OrderState.DELIVERED`, `OrderState.CANCELLED`, and `OrderState.REFUNDED` must have zero valid transitions (`can_transition` returns False for any target state).
""",
        "mutant_desc": "Allows transitioning from CANCELLED to PENDING",
        "mutant_patch": """--- a/processor/state.py
+++ b/processor/state.py
@@ -18,3 +18,3 @@
-    OrderState.CANCELLED: set(),
+    OrderState.CANCELLED: {OrderState.PENDING},
""",
    },

    # 5. mock_contract (4)
    {
        "id": "case_17",
        "project": "project_a",
        "category": "mock_contract",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.api.AppService.handle_request",
        "req_text": """# Requirement: Auth Login HTTP API Contract
Calling `AppService.handle_request("POST", "/auth/login", payload={"username": "...", "password": "..."})` for an existing registered user must return:
- `status`: 200
- `data`: dictionary containing key `"token"` with a non-empty string value.
""",
        "mutant_desc": "Returns status 500 on login endpoint",
        "mutant_patch": """--- a/app/api.py
+++ b/app/api.py
@@ -16,3 +16,3 @@
-            return {"status": 200, "data": {"token": tok}}
+            return {"status": 500, "data": {"token": tok}}
""",
    },
    {
        "id": "case_18",
        "project": "project_a",
        "category": "mock_contract",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.api.AppService.handle_request",
        "req_text": """# Requirement: Protected Route Authentication Contract
Accessing protected endpoints (such as `POST /inventory/items`) without a valid authentication token must return:
- `status`: 401
- `error`: "Unauthorized"
""",
        "mutant_desc": "Fails to return 401 for unauthenticated requests, returning 200 instead",
        "mutant_patch": """--- a/app/api.py
+++ b/app/api.py
@@ -21,3 +21,3 @@
-            return {"status": 401, "error": "Unauthorized"}
+            return {"status": 200, "error": "Unauthorized"}
""",
    },
    {
        "id": "case_19",
        "project": "project_a",
        "category": "mock_contract",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "app.api.AppService.handle_request",
        "req_text": """# Requirement: Inventory Restock API Contract
Calling `POST /inventory/restock` with a valid token and payload `{"sku": "SKU1", "amount": 5}` must update inventory and return:
- `status`: 200
- `data`: dict containing updated item with increased `quantity`.
""",
        "mutant_desc": "Returns status 204 instead of 200 on restock",
        "mutant_patch": """--- a/app/api.py
+++ b/app/api.py
@@ -34,3 +34,3 @@
-            return {"status": 200, "data": item}
+            return {"status": 204, "data": item}
""",
    },
    {
        "id": "case_20",
        "project": "project_a",
        "category": "mock_contract",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "app.api.AppService.handle_request",
        "req_text": """# Requirement: 404 Endpoint Not Found Contract
Requesting an unknown path (e.g. `GET /unknown/path`) with a valid token must return `{"status": 404, "error": "Endpoint not found"}`.
""",
        "mutant_desc": "Returns status 200 instead of 404 on unknown endpoint",
        "mutant_patch": """--- a/app/api.py
+++ b/app/api.py
@@ -36,3 +36,3 @@
-        return {"status": 404, "error": "Endpoint not found"}
+        return {"status": 200, "error": "Endpoint not found"}
""",
    },

    # 6. security_injection (4)
    {
        "id": "case_21",
        "project": "project_a",
        "category": "security_injection",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: Duplicate Username Rejection
The `UserManager.register` method must reject registration attempts where the `username` already exists, raising `ValueError("Username already exists")`.
""",
        "mutant_desc": "Allows overwriting existing user on duplicate username",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -20,4 +20,2 @@
-        if username in self._users:
-            raise ValueError("Username already exists")
""",
    },
    {
        "id": "case_22",
        "project": "project_a",
        "category": "security_injection",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: Duplicate Email Across Different Usernames Rejection
The `UserManager.register` method must reject registration when an email is already registered, even if the new attempt provides a different username, raising `ValueError("Email already registered")`.
""",
        "mutant_desc": "Allows duplicate email registration across different usernames",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -18,4 +18,2 @@
-        if any(u["email"] == email for u in self._users.values()):
-            raise ValueError("Email already registered")
""",
    },
    {
        "id": "case_23",
        "project": "project_a",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "app.auth.UserManager.register",
        "req_text": """# Requirement: Salted Password Hashing Security
When two users register with the identical password, their stored `password_hash` values must be distinct due to unique per-user cryptographic salts.
""",
        "mutant_desc": "Uses static constant salt resulting in identical hashes for identical passwords",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -22,3 +22,3 @@
-        salt = secrets.token_hex(8)
+        salt = "static_salt_constant"
""",
    },
    {
        "id": "case_24",
        "project": "project_a",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "app.auth.UserManager.authenticate",
        "req_text": """# Requirement: Invalid Token Rejection
The `UserManager.authenticate(token)` method must return `None` when presented with a forged or invalid token, preventing unauthorized access.
""",
        "mutant_desc": "Authenticates invalid token as first user in system",
        "mutant_patch": """--- a/app/auth.py
+++ b/app/auth.py
@@ -47,3 +47,3 @@
-        if not username:
-            return None
+        if not username and self._users:
+            return next(iter(self._users.values()))
""",
    },
]

def main():
    case_ids = []
    smoke_case_ids = ["case_01", "case_02"]

    for item in CASES:
        cid = item["id"]
        case_ids.append(cid)

        # 1. Write requirement
        req_rel = f"evals/requirements/req_{cid}.md"
        req_file = ROOT / req_rel
        req_file.write_text(item["req_text"].strip() + "\n", encoding="utf-8")

        # 2. Write mutant patch
        mut_rel = f"evals/mutants/mut_{cid}.patch"
        mut_file = ROOT / mut_rel
        mut_file.write_text(item["mutant_patch"].lstrip(), encoding="utf-8")

        # 3. Write case yaml
        case_yaml_data = {
            "case_id": cid,
            "project_name": item["project"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "split": item["split"],
            "requirement_path": req_rel,
            "target_entrypoint": item["entrypoint"],
            "timeout_sec": 60,
            "mutants": [
                {
                    "mutant_id": f"mut_{cid}",
                    "description": item["mutant_desc"],
                    "patch_path": mut_rel,
                }
            ],
            "tags": [item["category"], item["difficulty"], item["split"]],
        }

        case_file = CASE_DIR / f"{cid}.yaml"
        case_file.write_text(yaml.dump(case_yaml_data, sort_keys=False), encoding="utf-8")

    # 4. Write smoke suite
    smoke_data = {
        "suite_id": "smoke_v1",
        "description": "Fast smoke verification suite (2 cases: 1 project_a, 1 project_b)",
        "cases": smoke_case_ids,
        "default_repeats": 1,
        "default_timeout_sec": 60,
    }
    (SUITE_DIR / "smoke_v1.yaml").write_text(yaml.dump(smoke_data, sort_keys=False), encoding="utf-8")

    # 5. Write full benchmark suite
    bench_data = {
        "suite_id": "benchmark_v1",
        "description": "Comprehensive TestTeller Benchmark v1 (24 cases, stratified across 6 categories)",
        "cases": case_ids,
        "default_repeats": 3,
        "default_timeout_sec": 60,
    }
    (SUITE_DIR / "benchmark_v1.yaml").write_text(yaml.dump(bench_data, sort_keys=False), encoding="utf-8")

    print(f"Successfully generated {len(case_ids)} benchmark cases, requirements, mutants, and suites.")

if __name__ == "__main__":
    main()
