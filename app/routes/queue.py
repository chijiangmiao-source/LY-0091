import falcon
import json
from datetime import datetime, timedelta
from app.config import OVER_TIME_MINUTES
from app.models import (
    QueueRecord, FittingRoom, Store, QUEUE_STATUS, QUEUE_SOURCE, ROOM_STATUS,
    get_no_show_count_with_penalty
)
from app.routes.member import check_blacklist, record_behavior, get_or_create_member


FAIR_CALL_RATIO = 2


async def generate_ticket_number(store_id=None):
    now = datetime.now()
    date_prefix = now.strftime("%Y%m%d")
    prefix = f"A{date_prefix}"

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    today_count = await QueueRecord.objects.filter(
        queue_time__gte=today_start,
        queue_time__lt=today_end
    ).count()

    sequence = today_count + 1
    suffix = f"{sequence:04d}"
    ticket_number = f"{prefix}{suffix}"

    exists = await QueueRecord.objects.filter(ticket_number=ticket_number).exists()
    if exists:
        max_record = await QueueRecord.objects.filter(
            ticket_number__startswith=prefix
        ).order_by("-ticket_number").first()
        if max_record:
            last_seq = int(max_record.ticket_number[-4:])
            sequence = last_seq + 1
            suffix = f"{sequence:04d}"
            ticket_number = f"{prefix}{suffix}"

    return ticket_number


async def get_fair_next_record(store_id=None):
    waiting_query = QueueRecord.objects.filter(status="waiting").select_related("store")
    if store_id is not None:
        waiting_query = waiting_query.filter(store__id=store_id)

    appointment_waiting = await waiting_query.filter(
        source="appointment"
    ).order_by("queue_time").all()
    onsite_waiting = await waiting_query.filter(
        source="on_site"
    ).order_by("queue_time").all()

    called_query = QueueRecord.objects.filter(status__in=["called", "entered", "left"]).select_related("store")
    if store_id is not None:
        called_query = called_query.filter(store__id=store_id)

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    recent_called = await called_query.filter(
        call_time__gte=today_start
    ).order_by("-call_time").limit(FAIR_CALL_RATIO * 2).all()

    recent_appointment_count = sum(1 for r in recent_called if r.source == "appointment")
    recent_onsite_count = sum(1 for r in recent_called if r.source == "on_site")

    if appointment_waiting and onsite_waiting:
        if recent_appointment_count >= recent_onsite_count:
            return onsite_waiting[0]
        else:
            return appointment_waiting[0]
    elif appointment_waiting:
        return appointment_waiting[0]
    elif onsite_waiting:
        return onsite_waiting[0]
    else:
        return None


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
            data["source_text"] = QUEUE_SOURCE.get(r.source, r.source)
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

        blacklist_result = await check_blacklist(phone, "queue")
        if blacklist_result["is_blocked"]:
            raise falcon.HTTPBadRequest(
                title="取号失败",
                description=f"该手机号已被加入黑名单，无法现场取号。原因：{blacklist_result['reason']}"
            )
        if blacklist_result["is_gray"]:
            need_verify = data.get("verify_code")
            if not need_verify:
                raise falcon.HTTPBadRequest(
                    title="需要二次校验",
                    description=f"该手机号处于灰名单，需要工作人员确认后方可取号。原因：{blacklist_result['reason']}"
                )

        penalty_info = await get_no_show_count_with_penalty(phone)
        penalty = penalty_info["penalty"]
        if not penalty["can_onsite"]:
            raise falcon.HTTPBadRequest(
                title="取号失败",
                description=f"您近30天内爽约次数已达{penalty_info['no_show_count']}次，"
                           f"当前处于【{penalty['name']}】状态，暂无法现场取号。"
                           f"请联系工作人员处理或等待{penalty.get('ban_days', 30)}天后自动解封。"
            )

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

        ticket_number = data.get("ticket_number") or await generate_ticket_number(data.get("store_id"))
        source = data.get("source") or "on_site"

        record = QueueRecord(
            ticket_number=ticket_number,
            store=store,
            customer_name=data.get("customer_name"),
            phone=phone,
            status="waiting",
            source=source,
            appointment_id=data.get("appointment_id")
        )
        await record.save()

        await get_or_create_member(phone, data.get("customer_name"))
        await record_behavior(
            phone=phone,
            behavior_type="fitting",
            related_id=record.id,
            store_name=store.name if store else None,
            detail=f"取号：{ticket_number}，来源：{QUEUE_SOURCE.get(source, source)}"
        )

        result = record.dict()
        result["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        result["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        result["no_show_warning"] = None
        if penalty_info["no_show_count"] > 0:
            result["no_show_warning"] = (
                f"您近30天内爽约{penalty_info['no_show_count']}次，"
                f"当前处于【{penalty['name']}】状态。"
                f"再爽约{penalty_info['remain_times']}次将被封禁。"
            )

        resp.media = {"code": 0, "message": "取号成功", "data": result}


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
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)

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

        store_id = record.store.id if record.store else None
        fair_next = await get_fair_next_record(store_id)

        if not fair_next:
            raise falcon.HTTPBadRequest(title="叫号失败", description="当前无等待排队")

        if fair_next.id != record.id:
            raise falcon.HTTPBadRequest(
                title="叫号失败",
                description=f"根据公平策略，当前应叫号：{fair_next.ticket_number}（{fair_next.get_source_text()}），请按系统推荐顺序叫号"
            )

        record.status = "called"
        record.call_time = datetime.now()
        await record.update()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        resp.media = {"code": 0, "message": "叫号成功", "data": data}


class QueueNextCallResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")

        next_record = await get_fair_next_record(store_id)

        if not next_record:
            resp.media = {"code": 0, "message": "当前无等待排队", "data": None}
            return

        waiting_query = QueueRecord.objects.filter(status="waiting").select_related("store")
        if store_id is not None:
            waiting_query = waiting_query.filter(store__id=store_id)

        appointment_count = await waiting_query.filter(source="appointment").count()
        onsite_count = await waiting_query.filter(source="on_site").count()

        data = next_record.dict()
        if next_record.store:
            data["store_name"] = next_record.store.name
        data["status_text"] = QUEUE_STATUS.get(next_record.status, next_record.status)
        data["source_text"] = QUEUE_SOURCE.get(next_record.source, next_record.source)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "next_record": data,
                "appointment_waiting_count": appointment_count,
                "onsite_waiting_count": onsite_count,
                "fair_ratio": f"1:1 (预约:现场交替)",
                "suggestion": "请按公平策略依次叫号，系统已禁止跳过叫号"
            }
        }


class QueueAutoCallResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            data = {}
        store_id = data.get("store_id") if isinstance(data, dict) else None

        next_record = await get_fair_next_record(store_id)

        if not next_record:
            resp.media = {"code": 0, "message": "当前无等待排队", "data": None}
            return

        next_record.status = "called"
        next_record.call_time = datetime.now()
        await next_record.update()

        waiting_query = QueueRecord.objects.filter(status="waiting").select_related("store")
        if store_id is not None:
            waiting_query = waiting_query.filter(store__id=store_id)

        appointment_count = await waiting_query.filter(source="appointment").count()
        onsite_count = await waiting_query.filter(source="on_site").count()

        result = next_record.dict()
        if next_record.store:
            result["store_name"] = next_record.store.name
        result["status_text"] = QUEUE_STATUS.get(next_record.status, next_record.status)
        result["source_text"] = QUEUE_SOURCE.get(next_record.source, next_record.source)

        resp.media = {
            "code": 0,
            "message": f"已自动叫号：{next_record.ticket_number}（{next_record.get_source_text()}）",
            "data": {
                "called_record": result,
                "appointment_waiting_count": appointment_count,
                "onsite_waiting_count": onsite_count,
                "fair_ratio": "1:1 (预约:现场交替)"
            }
        }


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
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
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
        record.ticket_number = await generate_ticket_number(record.store.id if record.store else None)
        record.queue_time = datetime.now()
        record.call_time = None
        record.enter_time = None
        record.fitting_room = None
        record.remark = f"重新排队，原号码：{old_ticket}（过号重排，排在队尾）"
        await record.update()

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
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
            d["source_text"] = QUEUE_SOURCE.get(r.source, r.source)
            waiting_list.append(d)

        called_list = []
        for r in called:
            d = r.dict()
            if r.store:
                d["store_name"] = r.store.name
            d["status_text"] = "已叫号"
            d["source_text"] = QUEUE_SOURCE.get(r.source, r.source)
            called_list.append(d)

        appointment_waiting = len([x for x in waiting_list if x.get("source") == "appointment"])
        onsite_waiting = len([x for x in waiting_list if x.get("source") == "on_site"])

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "waiting_count": len(waiting_list),
                "called_count": len(called_list),
                "appointment_waiting_count": appointment_waiting,
                "onsite_waiting_count": onsite_waiting,
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


class QueueSourceResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in QUEUE_SOURCE.items()]
        }
