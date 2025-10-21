"""SQLAlchemy models for user and role-based access control."""

from sqlalchemy import Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, List

from fastapi_users import models

class User(Base):
    """User model."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    roles: Mapped[List["Role"]] = relationship("Role", secondary="user_roles")

class UserCreate(models.BaseUserCreate):
    pass

class UserUpdate(models.BaseUserUpdate):
    pass

class UserDB(User, models.BaseUserDB):
    pass

class Role(Base):
    """Role model."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    permissions: Mapped[List["Permission"]] = relationship("Permission", secondary="role_permissions")

class Permission(Base):
    """Permission model."""
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

class UserRoles(Base):
    """Association table between users and roles."""
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"))

class RolePermissions(Base):
    """Association table between roles and permissions."""
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"))
    permission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("permissions.id"))
