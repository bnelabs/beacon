"""Authentication logic using fastapi-users."""

import os
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import JWTAuthentication
from fastapi_users.db import SQLAlchemyUserDatabase

from database import database
from models.user import User, UserCreate, UserUpdate, UserDB

SECRET = os.getenv("SECRET_KEY", "a_very_secret_key")

user_db = SQLAlchemyUserDatabase(UserDB, database, users=User.__table__)

jwt_authentication = JWTAuthentication(
    secret=SECRET, lifetime_seconds=3600, tokenUrl="/auth/jwt/login"
)

fastapi_users = FastAPIUsers(
    user_db,
    [jwt_authentication],
    User,
    UserCreate,
    UserUpdate,
    UserDB,
)
