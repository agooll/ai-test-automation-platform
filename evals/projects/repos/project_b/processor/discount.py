from typing import Optional

class DiscountCalculator:
    @staticmethod
    def calculate_discount(total_amount: float, coupon_code: Optional[str] = None, is_vip: bool = False) -> float:
        if total_amount < 0:
            raise ValueError("Total amount cannot be negative")
        if total_amount == 0:
            return 0.0

        rate = 0.0
        if is_vip:
            rate += 0.10  # 10% VIP discount

        fixed_deduction = 0.0
        if coupon_code:
            code = coupon_code.strip().upper()
            if code == "SAVE10":
                rate += 0.10
            elif code == "FLAT20":
                fixed_deduction = 20.0
            elif code == "HALF":
                rate += 0.50
            else:
                raise ValueError(f"Unknown coupon code '{coupon_code}'")

        discount = (total_amount * rate) + fixed_deduction
        # Discount cannot exceed total amount
        return min(discount, total_amount)
