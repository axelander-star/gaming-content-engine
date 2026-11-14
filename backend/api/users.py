"""User management (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from api.deps import Admin, AppSettings, DbSession, csrf_protect
from api.schemas import UserOut
from core.enums import UserRole
from core.security import WeakPasswordError, hash_password, validate_password_policy
from models.access import User
from services import audit

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(csrf_protect)])


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)
    role: UserRole = UserRole.VIEWER
    display_name: str | None = Field(default=None, max_length=120)


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=1024)


def _check_password(password: str, min_length: int) -> None:
    try:
        validate_password_policy(password, min_length)
    except WeakPasswordError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def _active_admins(db: DbSession) -> int:
    return (
        db.scalar(select(func.count()).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
        or 0
    )


@router.get("", response_model=list[UserOut])
def list_users(_: Admin, db: DbSession) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: Admin, db: DbSession, settings: AppSettings) -> User:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already exists")
    _check_password(body.password, settings.password_min_length)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        "user.create",
        user_id=admin.id,
        entity_type="users",
        entity_id=user.id,
        after={"email": email, "role": body.role.value},
    )
    db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, admin: Admin, db: DbSession, settings: AppSettings
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    before = {"role": user.role.value, "is_active": user.is_active}

    loses_admin = user.role == UserRole.ADMIN and (
        (body.role is not None and body.role != UserRole.ADMIN) or body.is_active is False
    )
    if loses_admin and _active_admins(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cannot remove the last admin")

    invalidate = False
    if body.role is not None and body.role != user.role:
        user.role = body.role
        invalidate = True
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        invalidate = True
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.password is not None:
        _check_password(body.password, settings.password_min_length)
        user.password_hash = hash_password(body.password)
        invalidate = True
    if invalidate:
        user.session_version += 1  # force re-login with the new permissions

    audit.record(
        db,
        "user.update",
        user_id=admin.id,
        entity_type="users",
        entity_id=user.id,
        before=before,
        after={
            "role": user.role.value,
            "is_active": user.is_active,
            "password_changed": body.password is not None,
        },
    )
    db.commit()
    return user
