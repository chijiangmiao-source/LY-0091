import falcon

from app.exceptions import BusinessError
from app.services import member_service
from app.models import (
    MemberProfile, MEMBER_TAG_DEFINITIONS, BLACKLIST_STATUS, BLACKLIST_REASON,
    BEHAVIOR_TYPES, BLACKLIST_ACTIONS
)


async def get_or_create_member(phone: str, customer_name: str = None):
    return await member_service.get_or_create_member(phone, customer_name)


async def record_behavior(phone: str, behavior_type: str, detail: str = None,
                          related_id: int = None, store_name: str = None,
                          user_id: int = None):
    return await member_service.record_behavior(
        phone, behavior_type, detail, related_id, store_name, user_id
    )


async def refresh_member_stats(phone: str):
    return await member_service.refresh_member_stats(phone)


async def check_blacklist(phone: str, scene: str = "appointment") -> dict:
    return await member_service.check_blacklist(phone, scene)


class MemberListResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        blacklist_status = req.get_param("blacklist_status")
        tag = req.get_param("tag")
        keyword = req.get_param("keyword")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        query = MemberProfile.objects.select_related("blacklist_by", "unblacklist_by")

        if phone:
            query = query.filter(phone__contains=phone)
        if blacklist_status:
            query = query.filter(blacklist_status=blacklist_status)
        if keyword:
            query = query.filter(customer_name__contains=keyword)
        if tag:
            query = query.filter(tags__contains=tag)

        total = await query.count()
        records = await query.order_by("-updated_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for r in records:
            data = r.dict()
            data["tags_list"] = r.get_tags_list()
            data["tag_details"] = [
                {"key": t, **MEMBER_TAG_DEFINITIONS.get(t, {"name": t, "color": "default", "description": ""})}
                for t in r.get_tags_list()
            ]
            data["blacklist_status_text"] = r.get_blacklist_status_text()
            result.append(data)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": result
            }
        }


class MemberDetailResource:
    async def on_get(self, req, resp, member_id):
        try:
            data = await member_service.get_member_detail(member_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_put(self, req, resp, member_id):
        try:
            member = await MemberProfile.objects.get(id=member_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="会员不存在")

        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        if data.get("customer_name"):
            member.customer_name = data["customer_name"]
        if data.get("remark") is not None:
            member.remark = data["remark"]

        from datetime import datetime
        member.updated_at = datetime.now()
        await member.update()

        resp.media = {"code": 0, "message": "更新成功", "data": member.dict()}


class MemberPhoneResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        member = await get_or_create_member(phone)
        await refresh_member_stats(phone)

        member = await MemberProfile.objects.select_related("blacklist_by", "unblacklist_by").get(id=member.id)
        data = member.dict()
        data["tags_list"] = member.get_tags_list()
        data["tag_details"] = [
            {"key": t, **MEMBER_TAG_DEFINITIONS.get(t, {"name": t, "color": "default", "description": ""})}
            for t in member.get_tags_list()
        ]
        data["blacklist_status_text"] = member.get_blacklist_status_text()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class MemberRefreshResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        phone = data.get("phone")
        if phone:
            member = await refresh_member_stats(phone)
            if member:
                resp.media = {"code": 0, "message": "刷新成功", "data": member.dict()}
                return

        count = await member_service.refresh_all_members()
        resp.media = {"code": 0, "message": f"已刷新{count}个会员画像"}


class MemberBehaviorResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        behavior_type = req.get_param("behavior_type")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        from app.models import MemberBehavior
        query = MemberBehavior.objects.filter(phone=phone)
        if behavior_type:
            query = query.filter(behavior_type=behavior_type)

        total = await query.count()
        records = await query.order_by("-recorded_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for r in records:
            data = r.dict()
            data["behavior_type_text"] = BEHAVIOR_TYPES.get(r.behavior_type, r.behavior_type)
            result.append(data)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": result
            }
        }

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        phone = (data.get("phone") or "").strip()
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        behavior_type = (data.get("behavior_type") or "").strip()
        if behavior_type not in BEHAVIOR_TYPES:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的行为类型")

        member = await get_or_create_member(phone, data.get("customer_name"))

        user_id = None
        if hasattr(req, 'context') and req.context.get("user"):
            user_id = req.context["user"].id

        behavior = await record_behavior(
            phone=phone,
            behavior_type=behavior_type,
            detail=data.get("detail"),
            related_id=data.get("related_id"),
            store_name=data.get("store_name"),
            user_id=user_id
        )

        await refresh_member_stats(phone)

        resp.media = {"code": 0, "message": "记录成功", "data": behavior.dict()}


class BlacklistManageResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        operator = None
        if hasattr(req, 'context') and req.context.get("user"):
            operator = req.context["user"]

        try:
            member = await member_service.manage_blacklist(
                phone=(data.get("phone") or "").strip(),
                action=(data.get("action") or "").strip(),
                reason=(data.get("reason") or "").strip(),
                customer_name=data.get("customer_name"),
                operator=operator,
            )
        except BusinessError as e:
            raise e.to_http()

        result = member.dict()
        result["tags_list"] = member.get_tags_list()
        result["blacklist_status_text"] = member.get_blacklist_status_text()

        resp.media = {"code": 0, "message": "操作成功", "data": result}


class BlacklistCheckResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        scene = req.get_param("scene") or "appointment"

        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        result = await check_blacklist(phone, scene)
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class MemberStatsResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 30

        try:
            result = await member_service.get_member_stats(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class MemberTagDefinitionsResource:
    async def on_get(self, req, resp):
        result = [
            {"key": k, **v}
            for k, v in MEMBER_TAG_DEFINITIONS.items()
        ]
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class BlacklistStatusOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BLACKLIST_STATUS.items()]
        }


class BehaviorTypeOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BEHAVIOR_TYPES.items()]
        }


class BlacklistReasonOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BLACKLIST_REASON.items()]
        }
