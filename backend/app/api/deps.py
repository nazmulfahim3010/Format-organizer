from typing import Optional, Type, TypeVar

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import settings
from ..core.ratelimit import RateLimiter
from ..core.security import read_token
from ..database.session import get_db
from ..models.db import User

bearer = HTTPBearer(auto_error=False)
heavy_limiter = RateLimiter(settings.heavy_calls_per_minute, 60)
# failed sign-ins: per account, and (more loosely, offices share one address) per client address
login_failures = RateLimiter(settings.login_attempts_per_minute, 60)
login_failures_per_ip = RateLimiter(settings.login_attempts_per_minute * 5, 60)
T = TypeVar("T")


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    uid = read_token(creds.credentials, settings.secret) if creds else None
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def heavy(user: User = Depends(current_user)) -> User:
    """Rate limit for expensive operations (generation, preview, PDF)."""
    if not heavy_limiter.allow(str(user.id)):
        raise HTTPException(429, "Too many requests. Please wait a moment.")
    return user


def owned(db: Session, model: Type[T], obj_id, user: User, owner_field: str = "owner_id") -> T:
    """Fetch a row only if it belongs to the user. Other people's ids look like 404."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, owner_field) != user.id:
        raise HTTPException(404, "Not found.")
    return obj
