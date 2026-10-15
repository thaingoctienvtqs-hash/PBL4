from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.security import create_access_token, verify_password
from app.core.settings import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def user_response(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, email=user.email, full_name=user.full_name, is_active=user.is_active, roles=sorted(role.name for role in user.roles), created_at=user.created_at)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tên đăng nhập hoặc mật khẩu không đúng", headers={"WWW-Authenticate": "Bearer"})
    record_audit(db, user, "login", "session", detail="Đăng nhập thành công")
    db.commit()
    return LoginResponse(access_token=create_access_token(str(user.id)), expires_in=settings.jwt_expire_minutes * 60, user=user_response(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_response(user)


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record_audit(db, user, "logout", "session", detail="Đăng xuất phía client; access token hết hạn theo JWT")
    db.commit()
    return None
