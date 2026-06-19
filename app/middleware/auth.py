import falcon
from app.middleware.auth_utils import decode_access_token
from app.models import User


class AuthMiddleware:
    def __init__(self, exempt_paths=None):
        self.exempt_paths = exempt_paths or []

    async def process_resource(self, req, resp, resource, params):
        path = req.path
        for exempt in self.exempt_paths:
            if path.startswith(exempt):
                return

        auth_header = req.get_header("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise falcon.HTTPUnauthorized(
                title="未授权",
                description="请先登录"
            )

        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        if not payload:
            raise falcon.HTTPUnauthorized(
                title="Token无效",
                description="登录状态已过期，请重新登录"
            )

        user_id = payload.get("user_id")
        if not user_id:
            raise falcon.HTTPUnauthorized(
                title="Token无效",
                description="用户信息错误"
            )

        try:
            user = await User.objects.get(id=user_id)
            req.context["user"] = user
        except Exception:
            raise falcon.HTTPUnauthorized(
                title="用户不存在",
                description="用户已被删除，请重新登录"
            )
