import falcon
import json
from datetime import datetime, timedelta
from app.config import OVER_TIME_MINUTES
from app.models import QueueRecord, FittingRoom, Store, QUEUE_STATUS, ROOM_STATUS


def generate_ticket_number(store_id=None):
    now = datetime.now()
    prefix = now.strftime("%Y%m%d")
    import random
    suffix = ''.join([str(random.randint(0, 9)) for _ in range(4)])
    return f"A{prefix}{suffix}"


class QueueListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        status = req.get_param("status")
        phone = req.get_param("phone")

        query = QueueRecord.objects.select_related("store", "fitting_room")

        if store_id is not None:
            query = query.filter(store__id=store_id)
        if status:
            statuses = status.split(",")
            query = query.filter(status__in=statuses)
        if phone:
            query = query.filter(phone=phone)

        records = await query.order_by("queue_time").all()
        result = []
        for r in records:
            data = r.dict()
            if r.store:
                data["store_name"] = r.store.name
            if r.fitting_room:
                data["room_number"] = r.fitting_room.room_number
            data["status_text"] = QUEUE_STATUS.get(r.status, r.status)
            result.append(data)

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        phone = (data.get("phone") or "").strip()
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        exist_active = await QueueRecord.objects.filter(
            phone=phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise falcon.HTTPBadRequest(title="取号失败", description="该手机号已在排队中，不能重复取号")

        store = None
        if data.get("store_id"):
            try:
                store = await Store.objects.get(id=data.get("store_id"))
            except Exception:
                raise falcon.HTTPBadRequest(title="参数错误", description="门店不存在")

        ticket_number = data.get("ticket_number") or generate_ticket_number(data.get("store_id"))

        record = QueueRecord(
            ticket_number=ticket_number,
            store=store,
            customer_name=data.get("customer_name"),
            phone=phone,
            status="waiting"
        )
        await record.save()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        resp.media = {"code": 0, "message": "取号成功", "data": data}


class QueueDetailResource:
    async def on_get(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.select_related("store", "fitting_room").get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        data = record.dict()
        if record.store:
            data["store_name"] = record.store.name
        if record.fitting_room:
            data["room_number"] = record.fitting_room.room_number
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_delete(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status in ["entered"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="顾客已入场，请先处理离场")

        await record.delete()
        resp.media = {"code": 0, "message": "删除成功"}


class QueueCallResource:
    async def on_post(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status != "waiting":
            raise falcon.HTTPBadRequest(title="叫号失败", description="当前状态不支持叫号")

        record.status = "called"
        record.call_time = datetime.now()
        await record.update()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        resp.media = {"code": 0, "message": "叫号成功", "data": data}


class QueueEnterResource:
    async def on_post(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.select_related("fitting_room").get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status not in ["called", "waiting"]:
            raise falcon.HTTPBadRequest(title="入场失败", description="当前状态不支持入场")

        try:
            data = await req.get_media()
        except Exception:
            data = {}

        room_id = data.get("fitting_room_id")
        if not room_id:
            raise falcon.HTTPBadRequest(title="入场失败", description="请选择试衣间")

        try:
            room = await FittingRoom.objects.get(id=room_id)
        except Exception:
            raise falcon.HTTPBadRequest(title="入场失败", description="试衣间不存在")

        if not room.is_available():
            raise falcon.HTTPBadRequest(
                title="入场失败",
                description=f"试衣间当前状态：{ROOM_STATUS.get(room.status)}，无法使用"
            )

        if room.store and record.store and room.store.id != record.store.id:
            raise falcon.HTTPBadRequest(title="入场失败", description="试衣间不属于该门店")

        room.status = "occupied"
        await room.update()

        record.status = "entered"
        record.fitting_room = room
        record.enter_time = datetime.now()
        await record.update()

        result = record.dict()
        result["room_number"] = room.room_number
        result["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        resp.media = {"code": 0, "message": "入场登记成功", "data": result}


class QueueLeaveResource:
    async def on_post(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.select_related("fitting_room").get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status != "entered":
            raise falcon.HTTPBadRequest(title="离场失败", description="当前状态不支持离场操作")

        try:
            data = await req.get_media()
        except Exception:
            data = {}

        has_lost_item = data.get("has_lost_item", False)

        room = record.fitting_room
        if room:
            if has_lost_item:
                room.status = "sealed"
            else:
                room.status = "cleaning"
            await room.update()

        record.status = "left"
        record.leave_time = datetime.now()
        record.remark = data.get("remark")
        await record.update()

        result = record.dict()
        if room:
            result["room_number"] = room.room_number
            result["room_new_status"] = room.status
        result["status_text"] = QUEUE_STATUS.get(record.status, record.status)

        msg = "离场登记成功"
        if has_lost_item:
            msg += "，试衣间已封存，请登记遗留物"
        else:
            msg += "，请安排清理试衣间"

        resp.media = {"code": 0, "message": msg, "data": result}


class QueueOvertimeResource:
    async def on_post(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status not in ["waiting", "called"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="当前状态不支持标记过号")

        record.status = "overtime"
        record.is_overtime = True
        await record.update()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        resp.media = {"code": 0, "message": "已标记为过号", "data": data}


class QueueRequeueResource:
    async def on_post(self, req, resp, record_id):
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="排队记录不存在")

        if record.status != "overtime":
            raise falcon.HTTPBadRequest(title="操作失败", description="只有过号记录可以重新排队")

        exist_active = await QueueRecord.objects.filter(
            phone=record.phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise falcon.HTTPBadRequest(title="操作失败", description="该手机号已有进行中的排队")

        old_ticket = record.ticket_number
        record.status = "waiting"
        record.is_overtime = False
        record.ticket_number = generate_ticket_number(record.store.id if record.store else None)
        record.queue_time = datetime.now()
        record.call_time = None
        record.enter_time = None
        record.fitting_room = None
        record.remark = f"重新排队，原号码：{old_ticket}（过号重排，排在队尾）"
        await record.update()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        resp.media = {"code": 0, "message": "已重新排队（排在队尾，无法恢复原始位置）", "data": data}


class QueueWaitingListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")

        waiting_query = QueueRecord.objects.filter(status="waiting").select_related("store")
        called_query = QueueRecord.objects.filter(status="called").select_related("store")

        if store_id is not None:
            waiting_query = waiting_query.filter(store__id=store_id)
            called_query = called_query.filter(store__id=store_id)

        waiting = await waiting_query.order_by("queue_time").all()
        called = await called_query.order_by("call_time").all()

        waiting_list = []
        for r in waiting:
            d = r.dict()
            if r.store:
                d["store_name"] = r.store.name
            d["status_text"] = "排队中"
            waiting_list.append(d)

        called_list = []
        for r in called:
            d = r.dict()
            if r.store:
                d["store_name"] = r.store.name
            d["status_text"] = "已叫号"
            called_list.append(d)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "waiting_count": len(waiting_list),
                "called_count": len(called_list),
                "waiting_list": waiting_list,
                "called_list": called_list
            }
        }


class QueueStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in QUEUE_STATUS.items()]
        }
