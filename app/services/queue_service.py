from datetime import datetime, timedelta

from app.services.base import BaseService
from app.services.member_service import member_service
from app.exceptions import (
    NotFoundError, StateConflictError, ValidationError,
    BlacklistBlockedError, BlacklistGrayError, PenaltyBlockedError
)
from app.models import (
    QueueRecord, FittingRoom, Store, QUEUE_STATUS, QUEUE_SOURCE, ROOM_STATUS,
    get_no_show_count_with_penalty
)


FAIR_CALL_RATIO = 2


class QueueService(BaseService):

    async def generate_ticket_number(self, store_id=None) -> str:
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

    async def get_fair_next_record(self, store_id=None):
        waiting_query = QueueRecord.objects.filter(status="waiting").select_related("store")
        if store_id is not None:
            waiting_query = waiting_query.filter(store__id=store_id)

        appointment_waiting = await waiting_query.filter(
            source="appointment"
        ).order_by("queue_time").all()
        onsite_waiting = await waiting_query.filter(
            source="on_site"
        ).order_by("queue_time").all()

        called_query = QueueRecord.objects.filter(
            status__in=["called", "entered", "left"]
        ).select_related("store")
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

    async def create_queue_record(
        self,
        phone: str,
        customer_name: str = None,
        store_id: int = None,
        ticket_number: str = None,
        source: str = "on_site",
        appointment_id: int = None,
        verify_code: str = None
    ) -> dict:
        store = None
        if store_id:
            try:
                store = await Store.objects.get(id=store_id)
            except Exception:
                raise ValidationError("门店不存在")

        await member_service.validate_blacklist_for_scene(
            phone=phone,
            scene="queue",
            verify_code=verify_code,
            scene_label="现场取号"
        )

        penalty_info = await get_no_show_count_with_penalty(phone)
        penalty = penalty_info["penalty"]
        if not penalty["can_onsite"]:
            raise PenaltyBlockedError(
                description=f"您近30天内爽约次数已达{penalty_info['no_show_count']}次，"
                           f"当前处于【{penalty['name']}】状态，暂无法现场取号。"
                           f"请联系工作人员处理或等待{penalty.get('ban_days', 30)}天后自动解封。",
                scene="取号"
            )

        exist_active = await QueueRecord.objects.filter(
            phone=phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise StateConflictError("该手机号已在排队中，不能重复取号", title="取号失败")

        ticket_number = ticket_number or await self.generate_ticket_number(store_id)

        record = QueueRecord(
            ticket_number=ticket_number,
            store=store,
            customer_name=customer_name,
            phone=phone,
            status="waiting",
            source=source,
            appointment_id=appointment_id
        )
        await record.save()

        await member_service.get_or_create_member(phone, customer_name)
        await member_service.record_behavior(
            phone=phone,
            behavior_type="fitting",
            related_id=record.id,
            store_name=store.name if store else None,
            detail=f"取号：{ticket_number}，来源：{QUEUE_SOURCE.get(source, source)}"
        )

        self.log.info("create_queue", f"ticket={ticket_number}, phone={phone}")

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

        return result

    async def get_queue_record(self, record_id: int) -> dict:
        try:
            record = await QueueRecord.objects.select_related(
                "store", "fitting_room"
            ).get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        data = record.dict()
        if record.store:
            data["store_name"] = record.store.name
        if record.fitting_room:
            data["room_number"] = record.fitting_room.room_number
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        return data

    async def delete_queue_record(self, record_id: int):
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status in ["entered"]:
            raise StateConflictError("顾客已入场，请先处理离场", title="操作失败")

        await record.delete()
        self.log.info("delete_queue", f"record_id={record_id}")

    async def call_queue(self, record_id: int) -> dict:
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status != "waiting":
            raise StateConflictError("当前状态不支持叫号", title="叫号失败")

        store_id = record.store.id if record.store else None
        fair_next = await self.get_fair_next_record(store_id)

        if not fair_next:
            raise StateConflictError("当前无等待排队", title="叫号失败")

        if fair_next.id != record.id:
            raise StateConflictError(
                f"根据公平策略，当前应叫号：{fair_next.ticket_number}（{fair_next.get_source_text()}），请按系统推荐顺序叫号",
                title="叫号失败"
            )

        record.status = "called"
        record.call_time = datetime.now()
        await record.update()

        self.log.info("call_queue", f"ticket={record.ticket_number}")

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        return data

    async def get_next_call_info(self, store_id: int = None) -> dict:
        next_record = await self.get_fair_next_record(store_id)

        if not next_record:
            return None

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

        return {
            "next_record": data,
            "appointment_waiting_count": appointment_count,
            "onsite_waiting_count": onsite_count,
            "fair_ratio": f"1:1 (预约:现场交替)",
            "suggestion": "请按公平策略依次叫号，系统已禁止跳过叫号"
        }

    async def auto_call(self, store_id: int = None) -> dict:
        next_record = await self.get_fair_next_record(store_id)

        if not next_record:
            return None

        next_record.status = "called"
        next_record.call_time = datetime.now()
        await next_record.update()

        self.log.info("auto_call", f"ticket={next_record.ticket_number}")

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

        return {
            "called_record": result,
            "appointment_waiting_count": appointment_count,
            "onsite_waiting_count": onsite_count,
            "fair_ratio": "1:1 (预约:现场交替)"
        }

    async def enter_room(self, record_id: int, fitting_room_id: int) -> dict:
        try:
            record = await QueueRecord.objects.select_related("fitting_room").get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status not in ["called", "waiting"]:
            raise StateConflictError("当前状态不支持入场", title="入场失败")

        try:
            room = await FittingRoom.objects.get(id=fitting_room_id)
        except Exception:
            raise ValidationError("试衣间不存在", title="入场失败")

        if not room.is_available():
            raise StateConflictError(
                f"试衣间当前状态：{ROOM_STATUS.get(room.status)}，无法使用",
                title="入场失败"
            )

        if room.store and record.store and room.store.id != record.store.id:
            raise StateConflictError("试衣间不属于该门店", title="入场失败")

        room.status = "occupied"
        await room.update()

        record.status = "entered"
        record.fitting_room = room
        record.enter_time = datetime.now()
        await record.update()

        self.log.info("enter_room", f"ticket={record.ticket_number}, room={room.room_number}")

        result = record.dict()
        result["room_number"] = room.room_number
        result["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        return result

    async def leave_room(self, record_id: int, has_lost_item: bool = False, remark: str = None) -> dict:
        try:
            record = await QueueRecord.objects.select_related("fitting_room").get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status != "entered":
            raise StateConflictError("当前状态不支持离场操作", title="离场失败")

        room = record.fitting_room
        if room:
            if has_lost_item:
                room.status = "sealed"
            else:
                room.status = "cleaning"
            await room.update()

        record.status = "left"
        record.leave_time = datetime.now()
        record.remark = remark
        await record.update()

        self.log.info("leave_room", f"ticket={record.ticket_number}, has_lost_item={has_lost_item}")

        result = record.dict()
        if room:
            result["room_number"] = room.room_number
            result["room_new_status"] = room.status
        result["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        return result

    async def mark_overtime(self, record_id: int) -> dict:
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status not in ["waiting", "called"]:
            raise StateConflictError("当前状态不支持标记过号", title="操作失败")

        record.status = "overtime"
        record.is_overtime = True
        await record.update()

        await member_service.record_behavior(
            phone=record.phone,
            behavior_type="overtime",
            related_id=record.id,
            detail=f"排队过号：{record.ticket_number}"
        )
        self.log.info("mark_overtime", f"ticket={record.ticket_number}")

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        return data

    async def requeue(self, record_id: int) -> dict:
        try:
            record = await QueueRecord.objects.get(id=record_id)
        except Exception:
            raise NotFoundError("排队记录不存在")

        if record.status != "overtime":
            raise StateConflictError("只有过号记录可以重新排队", title="操作失败")

        exist_active = await QueueRecord.objects.filter(
            phone=record.phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise StateConflictError("该手机号已有进行中的排队", title="操作失败")

        old_ticket = record.ticket_number
        record.status = "waiting"
        record.is_overtime = False
        record.ticket_number = await self.generate_ticket_number(
            record.store.id if record.store else None
        )
        record.queue_time = datetime.now()
        record.call_time = None
        record.enter_time = None
        record.fitting_room = None
        record.remark = f"重新排队，原号码：{old_ticket}（过号重排，排在队尾）"
        await record.update()

        self.log.info("requeue", f"old_ticket={old_ticket}, new_ticket={record.ticket_number}")

        data = record.dict()
        data["status_text"] = QUEUE_STATUS.get(record.status, record.status)
        data["source_text"] = QUEUE_SOURCE.get(record.source, record.source)
        return data

    async def get_waiting_list(self, store_id: int = None) -> dict:
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

        return {
            "waiting_count": len(waiting_list),
            "called_count": len(called_list),
            "appointment_waiting_count": appointment_waiting,
            "onsite_waiting_count": onsite_waiting,
            "waiting_list": waiting_list,
            "called_list": called_list
        }

    async def list_queue_records(
        self,
        store_id: int = None,
        status: str = None,
        phone: str = None
    ) -> list:
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

        return result


queue_service = QueueService()
