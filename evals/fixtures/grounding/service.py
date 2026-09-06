"""User and Authentication Service for Stage 5 Grounding Benchmark."""

class UserService:
    def __init__(self, db_url: str):
        self.db_url = db_url

    def get_user_by_id(self, user_id: int) -> dict:
        if user_id <= 0:
            raise ValueError("Invalid user ID")
        return {"id": user_id, "username": f"user_{user_id}", "is_active": True}

    def create_user(self, username: str, email: str) -> dict:
        if not username or not email:
            raise ValueError("Username and email are required")
        return {"id": 101, "username": username, "email": email, "role": "member"}

    def delete_user(self, user_id: int) -> bool:
        if user_id <= 0:
            return False
        return True


class AuthService:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def verify_token(self, token: str) -> bool:
        return bool(token and token.startswith("Bearer "))

    def generate_token(self, user_id: int) -> str:
        return f"Bearer token_for_{user_id}"


class TokenManager:
    @staticmethod
    def validate(token: str) -> bool:
        return len(token) > 10
