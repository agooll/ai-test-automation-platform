import hashlib
import re
import secrets
from typing import Optional

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

class UserManager:
    def __init__(self):
        self._users: dict[str, dict] = {}
        self._tokens: dict[str, str] = {}

    def register(self, username: str, email: str, password: str) -> dict:
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not EMAIL_REGEX.match(email):
            raise ValueError("Invalid email format")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if any(u["email"] == email for u in self._users.values()):
            raise ValueError("Email already registered")
        if username in self._users:
            raise ValueError("Username already exists")

        salt = secrets.token_hex(8)
        hashed = hashlib.sha256((password + salt).encode()).hexdigest()
        user = {
            "username": username,
            "email": email,
            "salt": salt,
            "password_hash": hashed,
            "role": "user",
        }
        self._users[username] = user
        return {"username": username, "email": email, "role": "user"}

    def login(self, username: str, password: str) -> str:
        user = self._users.get(username)
        if not user:
            raise PermissionError("Invalid credentials")
        check_hash = hashlib.sha256((password + user["salt"]).encode()).hexdigest()
        if check_hash != user["password_hash"]:
            raise PermissionError("Invalid credentials")
        token = secrets.token_hex(16)
        self._tokens[token] = username
        return token

    def authenticate(self, token: str) -> Optional[dict]:
        username = self._tokens.get(token)
        if not username:
            return None
        user = self._users.get(username)
        if not user:
            return None
        return {"username": user["username"], "email": user["email"], "role": user["role"]}
