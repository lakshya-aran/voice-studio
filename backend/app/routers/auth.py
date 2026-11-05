from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import audit, client_ip, create_access_token, get_current_user, hash_password, rate_limiter, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "created_at": u.created_at}


@router.post("/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    rate_limiter.check(f"register:{client_ip(request)}", 10, 3600)
    email = body.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    audit("auth.register", user_id=user.id, request=request, db=db)
    return {"access_token": create_access_token(user.id), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    rate_limiter.check(f"login:{client_ip(request)}", 20, 300)
    user = db.scalars(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        audit("auth.login_failed", request=request, details={"email": body.email.lower()}, db=db)
        raise HTTPException(401, "Incorrect email or password")
    audit("auth.login", user_id=user.id, request=request, db=db)
    return {"access_token": create_access_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)
