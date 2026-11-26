"""认证与管理员权限依赖。"""
from fastapi import Depends, HTTPException, Request

from . import config, db


def current_user(request: Request):
    user = db.get_user_by_session(request.cookies.get(config.SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
