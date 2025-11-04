# Security Implementation Guide

## ⚠️ CRITICAL: Authentication Required for Production

**Current Status:** The BEACON platform currently has **NO AUTHENTICATION** implemented. All API endpoints are publicly accessible.

**Risk Level:** 🔴 **CRITICAL** - Do not deploy to production without implementing authentication.

---

## Immediate Actions Required

### 1. Authentication Implementation

The platform requires authentication middleware to be implemented before production deployment. Three approaches are recommended:

#### Option A: API Key Authentication (Simplest)
- **Difficulty:** Easy
- **Time to Implement:** 1-2 hours
- **Best For:** Internal tools, machine-to-machine communication
- **Implementation:**
  - Add `X-API-Key` header validation middleware
  - Store API keys in database with user association
  - Validate on every request

#### Option B: JWT (JSON Web Tokens) (Recommended)
- **Difficulty:** Medium
- **Time to Implement:** 4-6 hours
- **Best For:** Web applications with user sessions
- **Implementation:**
  - Add login endpoint that returns JWT
  - Validate JWT on protected endpoints
  - Include user ID and permissions in token
  - Use libraries like `python-jose` or `PyJWT`

#### Option C: OAuth 2.0 (Most Robust)
- **Difficulty:** Hard
- **Time to Implement:** 1-2 days
- **Best For:** Enterprise deployments, third-party integrations
- **Implementation:**
  - Implement OAuth 2.0 server or use external provider
  - Support multiple grant types
  - Token refresh mechanism

---

## Quick Start: Implementing API Key Authentication

### Step 1: Create Authentication Middleware

Create `/backend/middleware/auth.py`:

```python
from fastapi import Header, HTTPException, status
from typing import Optional

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key from request header."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key missing. Include X-API-Key header."
        )

    # TODO: Validate against database
    # For now, check against environment variable
    import os
    valid_key = os.getenv("BEACON_API_KEY")

    if not valid_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured on server"
        )

    if x_api_key != valid_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return x_api_key
```

### Step 2: Apply to Protected Routes

In `/backend/api/main.py`, add authentication dependency:

```python
from fastapi import Depends
from middleware.auth import verify_api_key

# Protected routes
app.include_router(
    jobs.router,
    prefix="/api/v1/jobs",
    tags=["Jobs"],
    dependencies=[Depends(verify_api_key)]  # Add this
)
```

### Step 3: Add API Key to Environment

Add to `.env`:
```bash
# API Authentication
# Generate a secure key: openssl rand -hex 32
BEACON_API_KEY=your-secure-api-key-here
```

### Step 4: Update Frontend

Add API key to frontend requests in `/frontend/src/hooks/useApi.js`:

```javascript
async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': 'your-api-key-here',  // Add this
      ...options.headers
    },
    ...options
  })
  // ... rest of code
}
```

---

## Production Authentication Checklist

Before deploying to production, ensure:

- [ ] Authentication middleware is implemented
- [ ] All sensitive endpoints require authentication
- [ ] API keys/tokens are stored securely (environment variables, not in code)
- [ ] Rate limiting is implemented to prevent brute force attacks
- [ ] Audit logging is enabled for all authenticated requests
- [ ] Token expiration and refresh mechanisms are in place (for JWT/OAuth)
- [ ] HTTPS is enforced (no HTTP in production)
- [ ] CORS is configured to allow only trusted origins
- [ ] Database credentials are strong and unique
- [ ] Database and Redis ports are not exposed to public

---

## Current Security Gaps

### Identified Issues (from Bug Report):

1. ✅ **FIXED:** Cancel job endpoint mismatch
2. ✅ **FIXED:** Datetime timezone inconsistency
3. ✅ **FIXED:** Missing CORS for production frontend (port 9876)
4. ✅ **FIXED:** Hardcoded API key in docker-compose.yml
5. ⚠️ **TODO:** No authentication middleware (this document addresses this)
6. ✅ **FIXED:** Weak default database credentials (documented)
7. ✅ **FIXED:** Exposed database ports (documented)

### Remaining TODOs in Code:

**File:** `/backend/api/routes/pipeline.py:80`
```python
started_by="user",  # TODO: Get from auth
```

**Action Required:** After implementing authentication, extract user ID from JWT/API key and use it here:
```python
# Get user from authentication context
user_id = request.state.user_id  # or from JWT claims
started_by=user_id,
```

---

## Security Best Practices

### 1. Never Store Secrets in Code
- ❌ Don't: `API_KEY = "abc123"` in code
- ✅ Do: `API_KEY = os.getenv("API_KEY")` from environment

### 2. Use Strong Passwords
- Minimum 16 characters
- Mix of uppercase, lowercase, numbers, special characters
- Generate with: `openssl rand -base64 32`

### 3. Principle of Least Privilege
- Users should only access what they need
- Implement role-based access control (RBAC)
- Different API keys for different services

### 4. Audit Everything
- Log all authentication attempts
- Log all sensitive operations (job creation, deletion, etc.)
- Monitor for suspicious patterns

### 5. Keep Dependencies Updated
- Regularly update Python packages
- Monitor security advisories
- Use `pip audit` or `safety` to check for vulnerabilities

---

## Testing Authentication

After implementing authentication, test:

1. **Unauthenticated Access:** Try accessing endpoints without credentials → Should get 401
2. **Invalid Credentials:** Try with wrong API key → Should get 403
3. **Valid Credentials:** Try with correct API key → Should work
4. **Rate Limiting:** Make many requests quickly → Should be throttled
5. **Token Expiration:** (For JWT) Wait for token to expire → Should require refresh

---

## Additional Security Measures

### Rate Limiting

Install and configure:
```bash
pip install slowapi
```

Add to FastAPI:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/v1/jobs")
@limiter.limit("10/minute")  # Max 10 job creations per minute
async def create_job(...):
    ...
```

### HTTPS Only

In production, enforce HTTPS:
```python
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware

if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(HTTPSRedirectMiddleware)
```

---

## Support

For security issues or questions:
1. Review this document
2. Check FastAPI security docs: https://fastapi.tiangolo.com/tutorial/security/
3. Consult the OWASP API Security Top 10

---

**Last Updated:** 2025-11-04
**Status:** Authentication not yet implemented - requires immediate attention before production
