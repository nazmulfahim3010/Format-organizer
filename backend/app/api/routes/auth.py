from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...core.security import burn_time, create_token, hash_password, needs_rehash, verify_password
from ...database.session import get_db
from ...models.db import User
from ...schemas.api import LoginIn, RegisterIn, TokenOut, UserOut
from ..deps import current_user, login_failures, login_failures_per_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _out(u: User) -> TokenOut:
    return TokenOut(token=create_token(u.id, settings.secret), user=UserOut(id=u.id, email=u.email, name=u.name))


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is closed.")
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "An account with this email already exists.")
    u = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return _out(u)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    if login_failures.blocked(email) or login_failures_per_ip.blocked(client):
        raise HTTPException(429, "Too many failed sign-in attempts. Please wait a minute.")
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        burn_time(body.password)          # same cost as a wrong password: no account enumeration by timing
    if u is None or not verify_password(body.password, u.password_hash):
        login_failures.record(email)
        login_failures_per_ip.record(client)
        raise HTTPException(401, "Wrong email or password.")
    if needs_rehash(u.password_hash):     # move old hashes to today's scrypt cost
        u.password_hash = hash_password(body.password)
        db.commit()
    return _out(u)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut(id=user.id, email=user.email, name=user.name)
