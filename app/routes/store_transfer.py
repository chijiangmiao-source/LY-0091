import falcon

from app.exceptions import BusinessError
from app.services import transfer_service
from app.models import (
    TRANSFER_STATUS, TRANSFER_SOURCE, STORE_LOAD_LEVEL,
    ROOM_TYPES
)


class TransferListResource:
    async def on_get(self, req, resp):
        status = req.get_param("status")
        source_store_id = req.get_param_as_int("source_store_id")
        target_store_id = req.get_param_as_int("target_store_id")
        phone = req.get_param("phone")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        try:
            result = await transfer_service.list_transfers(
                status=status,
                source_store_id=source_store_id,
                target_store_id=target_store_id,
                phone=phone,
                page=page,
                page_size=page_size,
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        source_type = data.get("source_type")
        if source_type == "queue":
            try:
                result = await transfer_service.create_transfer_for_queue(
                    queue_record_id=data.get("queue_record_id"),
                    target_store_id=data.get("target_store_id"),
                    transfer_reason=data.get("transfer_reason"),
                    customer_phone=data.get("customer_phone"),
                    customer_name=data.get("customer_name"),
                )
            except BusinessError as e:
                raise e.to_http()
        elif source_type == "appointment":
            try:
                result = await transfer_service.create_transfer_for_appointment(
                    appointment_id=data.get("appointment_id"),
                    target_store_id=data.get("target_store_id"),
                    transfer_reason=data.get("transfer_reason"),
                    customer_phone=data.get("customer_phone"),
                    customer_name=data.get("customer_name"),
                )
            except BusinessError as e:
                raise e.to_http()
        else:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的转单来源类型")

        resp.media = {"code": 0, "message": "转单申请创建成功，请等待顾客确认", "data": result}


class TransferDetailResource:
    async def on_get(self, req, resp, transfer_id):
        try:
            data = await transfer_service.get_transfer_detail(transfer_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class TransferCustomerConfirmResource:
    async def on_post(self, req, resp, transfer_id):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        try:
            confirmed = data.get("confirmed", True)
            note = data.get("note")
            result = await transfer_service.customer_confirm_transfer(
                transfer_id=transfer_id,
                confirmed=confirmed,
                note=note,
            )
        except BusinessError as e:
            raise e.to_http()

        if confirmed:
            msg = "顾客已确认转单，请等待目标门店承接"
        else:
            msg = "顾客已拒绝转单，建议在源门店继续排队"

        resp.media = {"code": 0, "message": msg, "data": result}


class TransferTargetAcceptResource:
    async def on_post(self, req, resp, transfer_id):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        user = None
        if hasattr(req, 'context') and req.context.get("user"):
            user = req.context["user"]

        try:
            accepted = data.get("accepted", True)
            reject_reason = data.get("reject_reason")
            result = await transfer_service.target_store_accept_transfer(
                transfer_id=transfer_id,
                accepted=accepted,
                reject_reason=reject_reason,
                user=user,
            )
        except BusinessError as e:
            raise e.to_http()

        if accepted:
            msg = "目标门店已承接，转单将立即执行"
        else:
            msg = "目标门店已拒绝承接，请安排其他门店或在源门店继续排队"

        resp.media = {"code": 0, "message": msg, "data": result}


class TransferExecuteResource:
    async def on_post(self, req, resp, transfer_id):
        user = None
        if hasattr(req, 'context') and req.context.get("user"):
            user = req.context["user"]

        try:
            result = await transfer_service.execute_transfer_by_id(
                transfer_id=transfer_id, user=user
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "转单执行成功", "data": result}


class TransferCancelResource:
    async def on_post(self, req, resp, transfer_id):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        try:
            result = await transfer_service.cancel_transfer(
                transfer_id=transfer_id,
                cancel_reason=data.get("cancel_reason", "操作员主动取消"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "转单已取消", "data": result}


class TransferRecommendStoresResource:
    async def on_get(self, req, resp):
        source_store_id = req.get_param_as_int("source_store_id")
        room_type = req.get_param("room_type") or "standard"
        phone = req.get_param("phone")
        limit = req.get_param_as_int("limit") or 5

        try:
            result = await transfer_service.recommend_target_stores(
                source_store_id=source_store_id,
                room_type=room_type,
                phone=phone,
                limit=limit,
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class TransferStoreLoadResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")

        try:
            if store_id:
                result = await transfer_service.get_store_load_info(store_id)
            else:
                from app.models import Store
                stores = await Store.objects.filter(is_active=True).all()
                result = []
                for s in stores:
                    info = await transfer_service.get_store_load_info(s.id)
                    result.append(info)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class TransferStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in TRANSFER_STATUS.items()]
        }


class TransferSourceResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in TRANSFER_SOURCE.items()]
        }


class TransferStoreLoadLevelResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v["label"]} for k, v in STORE_LOAD_LEVEL.items()]
        }
