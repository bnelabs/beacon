"""Authentication logic using fastapi-users."""

import os
from fastapi_users import FastAPIUsers, UserManager
from fastapi_users.authentication import JWTAuthentication
from fastapi_users.db import SQLAlchemyUserDatabase
from typing import Optional
from fastapi import Depends, Request

from database import database
from models.user import User, UserCreate, UserUpdate, UserDB

SECRET = os.getenv("SECRET_KEY", "a_very_secret_key")

class CustomUserManager(UserManager[UserDB, int]): # UserDB is the Pydantic model, int is the ID type
    async def on_after_register(self, user: UserDB, request: Optional[Request] = None):
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(self, user: UserDB, token: str, request: Optional[Request] = None):
        print(f"User {user.id} has forgot their password. Reset token: {token}")

async def get_user_db():
    yield SQLAlchemyUserDatabase(UserDB, database)

async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield CustomUserManager(user_db)

jwt_authentication = JWTAuthentication(
    secret=SECRET, lifetime_seconds=3600, tokenUrl="/auth/jwt/login"
)

fastapi_users = FastAPIUsers(
    get_user_manager,
    [jwt_authentication],
)
