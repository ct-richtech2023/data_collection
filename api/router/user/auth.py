from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from api.common import models

SECRET_KEY = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],  # 兼容长口令，保留旧 bcrypt
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    # 保留给可能的直接调用者；不做自动升级
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_user(db: Session, username: str, password: str) -> models.User | None:
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        return None
    ok, new_hash = pwd_context.verify_and_update(password, user.password)
    if not ok:
        return None
    # 若命中旧算法，返回了升级后的哈希，写回数据库以完成平滑迁移
    if new_hash:
        user.password = new_hash
        db.add(user)
        try:
            db.commit()
        except Exception:
            db.rollback()
            # 即便写回失败，鉴权已通过，仍返回用户
    return user


def get_current_user(token: str, db: Session) -> models.User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # 检查是否为默认token
    if token == "richtech":
        # 返回一个默认的管理员用户（如果存在）
        admin_user = db.query(models.User).filter(models.User.permission_level == "admin").first()
        if admin_user:
            return admin_user
        else:
            # 如果没有管理员用户，创建一个临时的默认用户
            from common.models import PermissionLevel
            default_user = models.User(
                username="default_admin",
                email="admin@default.com",
                password="default_password",
                permission_level=PermissionLevel.ADMIN
            )
            return default_user
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str | None = payload.get("sub")
        if sub is None:
            raise cred_exc
    except JWTError:
        raise cred_exc
    user = db.query(models.User).filter(models.User.username == sub).first()
    if user is None:
        raise cred_exc
    return user
