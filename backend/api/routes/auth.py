"""
Authentication routes for BEACON Platform

Provides login, token refresh, and user management endpoints.
"""

from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from database import get_db
from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    require_role,
    Token,
    TokenData,
    User,
    UserRole,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter()


# Request/Response Models
class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str = ""


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    roles: List[UserRole]
    disabled: bool


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


# Mock user database (replace with real database in production)
MOCK_USERS = {
    "admin": {
        "id": 1,
        "username": "admin",
        "email": "admin@beacon.com",
        "full_name": "System Administrator",
        "hashed_password": get_password_hash("admin123"),  # Change in production!
        "roles": [UserRole.ADMIN],
        "disabled": False,
    },
    "analyst": {
        "id": 2,
        "username": "analyst",
        "email": "analyst@beacon.com",
        "full_name": "Risk Analyst",
        "hashed_password": get_password_hash("analyst123"),
        "roles": [UserRole.ANALYST],
        "disabled": False,
    },
    "viewer": {
        "id": 3,
        "username": "viewer",
        "email": "viewer@beacon.com",
        "full_name": "Data Viewer",
        "hashed_password": get_password_hash("viewer123"),
        "roles": [UserRole.VIEWER],
        "disabled": False,
    },
}


def get_user(username: str):
    """Get user by username (mock implementation)."""
    return MOCK_USERS.get(username)


def authenticate_user(username: str, password: str):
    """Authenticate user with username and password."""
    user = get_user(username)
    if not user:
        return False
    if not verify_password(password, user["hashed_password"]):
        return False
    return user


@router.post("/login", response_model=Token, tags=["Authentication"])
async def login(credentials: LoginRequest):
    """
    Login with username and password.

    Returns JWT access token and refresh token.

    **Default Accounts:**
    - Username: `admin` / Password: `admin123` (Admin role)
    - Username: `analyst` / Password: `analyst123` (Analyst role)
    - Username: `viewer` / Password: `viewer123` (Viewer role)

    **⚠️ Change default passwords in production!**
    """
    user = authenticate_user(credentials.username, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user["disabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is disabled"
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["id"],
            "username": user["username"],
            "roles": [role.value for role in user["roles"]]
        },
        expires_delta=access_token_expires
    )

    # Create refresh token
    refresh_token = create_refresh_token(
        data={
            "sub": user["id"],
            "username": user["username"]
        }
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=Token, tags=["Authentication"])
async def refresh_token(request: RefreshTokenRequest):
    """
    Refresh access token using refresh token.

    Returns new access token and refresh token.
    """
    try:
        token_data = decode_token(request.refresh_token)

        # Get user to get latest roles
        user = get_user(token_data.username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        # Create new tokens
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": user["id"],
                "username": user["username"],
                "roles": [role.value for role in user["roles"]]
            },
            expires_delta=access_token_expires
        )

        refresh_token = create_refresh_token(
            data={
                "sub": user["id"],
                "username": user["username"]
            }
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@router.get("/me", response_model=UserResponse, tags=["Authentication"])
async def get_current_user_info(current_user: TokenData = Depends(get_current_active_user)):
    """
    Get current authenticated user information.
    """
    user = get_user(current_user.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        full_name=user["full_name"],
        roles=user["roles"],
        disabled=user["disabled"]
    )


@router.post("/logout", tags=["Authentication"])
async def logout(current_user: TokenData = Depends(get_current_active_user)):
    """
    Logout current user.

    In a production system, this would invalidate the token by adding it to a blacklist.
    For now, clients should delete the token from storage.
    """
    return {"message": "Successfully logged out. Please delete the token from client storage."}


@router.post("/change-password", tags=["Authentication"])
async def change_password(
    request: PasswordChangeRequest,
    current_user: TokenData = Depends(get_current_active_user)
):
    """
    Change current user's password.
    """
    user = get_user(current_user.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Verify current password
    if not verify_password(request.current_password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Hash new password
    new_hashed_password = get_password_hash(request.new_password)

    # Update password (mock implementation - in production, update database)
    MOCK_USERS[current_user.username]["hashed_password"] = new_hashed_password

    return {"message": "Password changed successfully"}


@router.get("/users", response_model=List[UserResponse], tags=["User Management"])
async def list_users(
    current_user: TokenData = Depends(require_role([UserRole.ADMIN]))
):
    """
    List all users (Admin only).
    """
    return [
        UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            full_name=user["full_name"],
            roles=user["roles"],
            disabled=user["disabled"]
        )
        for user in MOCK_USERS.values()
    ]


@router.post("/register", response_model=UserResponse, tags=["Authentication"], status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterRequest,
    current_user: TokenData = Depends(require_role([UserRole.ADMIN]))
):
    """
    Register new user (Admin only).
    """
    # Check if username already exists
    if request.username in MOCK_USERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Create new user
    new_user = {
        "id": len(MOCK_USERS) + 1,
        "username": request.username,
        "email": request.email,
        "full_name": request.full_name,
        "hashed_password": get_password_hash(request.password),
        "roles": [UserRole.VIEWER],  # Default role
        "disabled": False
    }

    MOCK_USERS[request.username] = new_user

    return UserResponse(
        id=new_user["id"],
        username=new_user["username"],
        email=new_user["email"],
        full_name=new_user["full_name"],
        roles=new_user["roles"],
        disabled=new_user["disabled"]
    )
