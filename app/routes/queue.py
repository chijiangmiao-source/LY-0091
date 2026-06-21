import falcon
import json

from app.exceptions import BusinessError
from app.services import queue_service
from app.models import QUEUE_STATUS, QUEUE_SOURCE


async def generate_ticket_number(store_id=None):
    return await queue_service.generate_ticket_number(store_id)


async def get_fair_next_record(store_id=None):
    return await queue_service.get_fair_next_record(store_id)


class QueueListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        status = req.get_param("status")
        phone = req.get_param("phone")

        try:
            result = await queue_service.list_queue_records(
                store_id=store_id, status=status, phone=phone
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        try:
            result = await queue_service.create_queue_record(
                phone=(data.get("phone") or "").strip(),
                customer_name=data.get("customer_name"),
                store_id=data.get("store_id"),
                ticket_number=data.get("ticket_number"),
                source=data.get("source") or "on_site",
                appointment_id=data.get("appointment_id"),
                verify_code=data.get("verify_code"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "取号成功", "data": result}


class QueueDetailResource:
    async def on_get(self, req, resp, record_id):
        try:
            data = await queue_service.get_queue_record(record_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_delete(self, req, resp, record_id):
        try:
            await queue_service.delete_queue_record(record_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "删除成功"}


class QueueCallResource:
    async def on_post(self, req, resp, record_id):
        try:
            data = await queue_service.call_queue(record_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "叫号成功", "data": data}


class QueueNextCallResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")

        try:
            result = await queue_service.get_next_call_info(store_id)
        except BusinessError as e:
            raise e.to_http()

        if not result:
            resp.media = {"code": 0, "message": "当前无等待排队", "data": None}
            return

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class QueueAutoCallResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            data = {}
        store_id = data.get("store_id") if isinstance(data, dict) else None

        try:
            result = await queue_service.auto_call(store_id)
        except BusinessError as e:
            raise e.to_http()

        if not result:
            resp.media = {"code": 0, "message": "当前无等待排队", "data": None}
            return

        called_record = result["called_record"]
        resp.media = {
            "code": 0,
            "message": f"已自动叫号：{called_record['ticket_number']}（{called_record['source_text']}）",
            "data": result
        }


class QueueEnterResource:
    async def on_post(self, req, resp, record_id):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        try:
            result = await queue_service.enter_room(
                record_id=record_id,
                fitting_room_id=data.get("fitting_room_id"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "入场登记成功", "data": result}


class QueueLeaveResource:
    async def on_post(self, req, resp, record_id):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        try:
            result = await queue_service.leave_room(
                record_id=record_id,
                has_lost_item=data.get("has_lost_item", False),
                remark=data.get("remark"),
            )
        except BusinessError as e:
            raise e.to_http()

        has_lost_item = data.get("has_lost_item", False)
        msg = "离场登记成功"
        if has_lost_item:
            msg += "，试衣间已封存，请登记遗留物"
        else:
            msg += "，请安排清理试衣间"

        resp.media = {"code": 0, "message": msg, "data": result}


class QueueOvertimeResource:
    async def on_post(self, req, resp, record_id):
        try:
            data = await queue_service.mark_overtime(record_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "已标记为过号", "data": data}


class QueueRequeueResource:
    async def on_post(self, req, resp, record_id):
        try:
            data = await queue_service.requeue(record_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "已重新排队（排在队尾，无法恢复原始位置）", "data": data}


class QueueWaitingListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")

        try:
            result = await queue_service.get_waiting_list(store_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class QueueStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in QUEUE_STATUS.items()]
        }


class QueueSourceResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in QUEUE_SOURCE.items()]
        }
