import falcon

from app.exceptions import BusinessError
from app.services import lost_item_service
from app.models import LOST_ITEM_STATUS, LOST_ITEM_HANDLING_METHOD


class LostItemListResource:
    async def on_get(self, req, resp):
        status = req.get_param("status")
        room_id = req.get_param_as_int("room_id")

        try:
            result = await lost_item_service.list_lost_items(status=status, room_id=room_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        user = None
        if hasattr(req, 'context') and req.context.get("user"):
            user = req.context["user"]

        try:
            result = await lost_item_service.register_lost_item(
                item_name=(data.get("item_name") or "").strip(),
                fitting_room_id=data.get("fitting_room_id"),
                queue_record_id=data.get("queue_record_id"),
                quantity=data.get("quantity") or 1,
                description=data.get("description"),
                found_by_user=user,
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "登记成功，请尽快封存并通知顾客认领", "data": result}


class LostItemDetailResource:
    async def on_get(self, req, resp, item_id):
        try:
            data = await lost_item_service.get_lost_item_detail(item_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_delete(self, req, resp, item_id):
        try:
            await lost_item_service.delete_lost_item(item_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "删除成功"}


class LostItemSealResource:
    async def on_post(self, req, resp, item_id):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        user = None
        if hasattr(req, 'context') and req.context.get("user"):
            user = req.context["user"]

        try:
            result = await lost_item_service.seal_lost_item(
                item_id=item_id,
                seal_location=data.get("seal_location"),
                seal_user=user,
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "封存成功，请及时通知顾客认领", "data": result}


class LostItemClaimResource:
    async def on_post(self, req, resp, item_id):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        user = None
        if hasattr(req, 'context') and req.context.get("user"):
            user = req.context["user"]

        try:
            result = await lost_item_service.claim_lost_item(
                item_id=item_id,
                claimant_name=(data.get("claimant_name") or "").strip(),
                claimant_phone=(data.get("claimant_phone") or "").strip(),
                claimant_id_card=(data.get("claimant_id_card") or "").strip(),
                claim_remark=data.get("claim_remark"),
                claim_user=user,
                verify_code=data.get("verify_code"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "认领成功，请提醒顾客注意保管随身物品", "data": result}


class LostItemDisposeResource:
    async def on_post(self, req, resp, item_id):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        try:
            result = await lost_item_service.dispose_lost_item(
                item_id=item_id,
                remark=data.get("remark"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "已按无主物品处理完成", "data": result}


class LostItemStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in LOST_ITEM_STATUS.items()]
        }


class LostItemHandlingMethodResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in LOST_ITEM_HANDLING_METHOD.items()]
        }
