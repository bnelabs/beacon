"""
Authentication and Authorization Module for BEACON Platform

Provides JWT-based authentication with role-based access control (RBAC).
Supports API key authentication for programmatic access.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum

from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel


# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# User Roles
class UserRole(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"
    API_USER = "api_user"


# Permissions by role
ROLE_PERMISSIONS = {
    UserRole.ADMIN: [
        "read:all",
        "write:all",
        "delete:all",
        "manage:users",
        "manage:datasources",
        "manage:jobs",
        "manage:models",
    ],
    UserRole.ANALYST: [
        "read:all",
        "write:jobs",
        "write:datasources",
        "read:models",
        "create:scenarios",
    ],
    UserRole.VIEWER: [
        "read:all",
    ],
    UserRole.API_USER: [
        "read:all",
        "write:jobs",
        "read:models",
    ],
}


# Pydantic Models
class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    roles: List[UserRole] = []


class User(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    disabled: bool = False
    roles: List[UserRole] = [UserRole.VIEWER]


class UserInDB(User):
    hashed_password: str


# Password hashing
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return pwd_context.hash(password)


# Token creation and verification
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> TokenData:
    """Decode and verify JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        username: str = payload.get("username")
        roles: List[str] = payload.get("roles", [])

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return TokenData(
            user_id=user_id,
            username=username,
            roles=[UserRole(role) for role in roles]
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Dependency for getting current user
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> TokenData:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    return decode_token(token)


async def get_current_active_user(
    current_user: TokenData = Depends(get_current_user)
) -> TokenData:
    """Get current active user (not disabled)."""
    # In production, check if user is disabled in database
    return current_user


# Role-based access control
def require_role(required_roles: List[UserRole]):
    """Dependency to require specific roles."""
    async def check_role(current_user: TokenData = Depends(get_current_active_user)):
        user_roles_set = set(current_user.roles)
        required_roles_set = set(required_roles)

        if not user_roles_set.intersection(required_roles_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {[r.value for r in required_roles]}"
            )
        return current_user

    return check_role


def require_permission(permission: str):
    """Dependency to require specific permission."""
    async def check_permission(current_user: TokenData = Depends(get_current_active_user)):
        user_permissions = set()
        for role in current_user.roles:
            user_permissions.update(ROLE_PERMISSIONS.get(role, []))

        # Check for wildcard permissions
        if "write:all" in user_permissions or "read:all" in user_permissions:
            return current_user

        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {permission}"
            )
        return current_user

    return check_permission


# API Key authentication (for programmatic access)
async def get_api_key_user(api_key: str = Security(api_key_header)) -> TokenData:
    """Authenticate using API key."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )

    # In production, validate API key against database
    # For now, check against environment variable
    valid_api_keys = os.getenv("VALID_API_KEYS", "").split(",")

    if api_key not in valid_api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # Return API user token data
    return TokenData(
        user_id=0,
        username="api_user",
        roles=[UserRole.API_USER]
    )


# Optional authentication (allows both authenticated and public access)
async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    api_key: Optional[str] = Security(api_key_header)
) -> Optional[TokenData]:
    """Get user if authenticated, otherwise None (for public endpoints)."""
    if api_key:
        return await get_api_key_user(api_key)

    if credentials:
        return await get_current_user(credentials)

    return None


# Utility functions
def has_permission(user: TokenData, permission: str) -> bool:
    """Check if user has specific permission."""
    user_permissions = set()
    for role in user.roles:
        user_permissions.update(ROLE_PERMISSIONS.get(role, []))

    return permission in user_permissions or "write:all" in user_permissions


def is_admin(user: TokenData) -> bool:
    """Check if user has admin role."""
    return UserRole.ADMIN in user.roles
