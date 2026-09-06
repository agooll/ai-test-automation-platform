# User Management Service Requirements

## Authentication
- Endpoints require Bearer token in the `Authorization` header.
- The login endpoint is `POST /api/v1/auth/login`.

## Users
- Fetch user via `GET /api/v1/users/{id}`.
- Create user via `POST /api/v1/users`.
- Delete user via `DELETE /api/v1/users/{id}`.
- Class `UserService` provides business logic.
- Class `AuthService` handles authentication and token verification.
