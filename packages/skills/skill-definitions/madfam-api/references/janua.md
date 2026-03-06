# Janua Authentication API

## Overview
Janua is the MADFAM authentication service. All services delegate auth to Janua.

## JWT Claims
- `sub`: User ID (UUID)
- `email`: User email
- `roles`: List of role strings
- `org_id`: Organization ID (UUID)

## Key Endpoints
- `POST /auth/login` — Issue JWT token pair
- `POST /auth/refresh` — Refresh access token
- `GET /auth/me` — Current user profile
- `POST /auth/logout` — Revoke tokens

## FastAPI Integration
```python
from nexus_api.auth import get_current_user

@router.get("/protected")
async def protected_route(user=Depends(get_current_user)):
    return {"user_id": user.sub}
```

## Next.js Integration
Use the Janua middleware in `middleware.ts` to validate session cookies.
The middleware extracts the JWT and validates it against Janua's JWKS endpoint.

## Ports
- 4100: Janua API
- 4101: Janua admin
- 4102-4104: Reserved
