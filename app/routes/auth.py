import falcon
import json
from datetime import datetime
from app.middleware.auth_utils import create_access_token
from app.models import User


class LoginResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not username or not password:
            raise falcon.HTTPBadRequest(title="参数错误", description="用户名和密码不能为空")

        try:
            user = await User.objects.get(username=username)
        except Exception:
            raise falcon.HTTPUnauthorized(title="登录失败", description="用户名或密码错误")

        if not user.check_password(password):
            raise falcon.HTTPUnauthorized(title="登录失败", description="用户名或密码错误")

        token = create_access_token({
            "user_id": user.id,
            "username": user.username,
            "role": user.role
        })

        resp.media = {
            "code": 0,
            "message": "登录成功",
            "data": {
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "real_name": user.real_name,
                    "role": user.role
                }
            }
        }


class UserInfoResource:
    async def on_get(self, req, resp):
        user = req.context["user"]
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "role": user.role
            }
        }
