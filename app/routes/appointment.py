import falcon
from datetime import datetime, timedelta, date
from app.models import (
    Appointment, NoShowRecord, AppointmentSlotConfig, Store,
    APPOINTMENT_STATUS, NO_SHOW_THRESHOLD, APPOINTMENT_TIMEOUT_MINUTES,
    MAX_FUTURE_DAYS, DEFAULT_TIME_SLOTS, ROOM_TYPES,
    QueueRecord, QUEUE_SOURCE, QUEUE_STATUS,
    get_no_show_count_with_penalty, get_no_show_penalty, NO_SHOW_PENALTY_LEVELS
)
from app.routes.queue import generate_ticket_number


async def generate_appointment_no():
    now = datetime.now()
    date_prefix = now.strftime("%Y%m%d")
    prefix = f"R{date_prefix}"

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    today_count = await Appointment.objects.filter(
        created_at__gte=today_start,
        created_at__lt=today_end
    ).count()

    sequence = today_count + 1
    suffix = f"{sequence:04d}"
    appointment_no = f"{prefix}{suffix}"

    exists = await Appointment.objects.filter(appointment_no=appointment_no).exists()
    if exists:
        max_record = await Appointment.objects.filter(
            appointment_no__startswith=prefix
        ).order_by("-appointment_no").first()
        if max_record:
            last_seq = int(max_record.appointment_no[-4:])
            sequence = last_seq + 1
            suffix = f"{sequence:04d}"
            appointment_no = f"{prefix}{suffix}"

    return appointment_no


async def get_no_show_count(phone: str, days: int = 30) -> int:
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    count = await NoShowRecord.objects.filter(
        phone=phone,
        appointment_date__gte=start_date
    ).count()
    return count


async def get_slot_capacity(store_id, room_type: str, time_slot: str) -> int:
    config = await AppointmentSlotConfig.objects.filter(
        store__id=store_id if store_id else None,
        room_type=room_type,
        time_slot=time_slot,
        is_active=True
    ).first()
    return config.capacity if config else 5


async def get_slot_booked_count(store_id, appointment_date: str, room_type: str, time_slot: str) -> int:
    query = Appointment.objects.filter(
        appointment_date=appointment_date,
        room_type=room_type,
        time_slot=time_slot,
        status__in=["pending", "confirmed"]
    )
    if store_id:
        query = query.filter(store__id=store_id)
    else:
        query = query.filter(store__isnull=True)
    return await query.count()


async def process_expired_appointments():
    now = datetime.now()
    pending_appointments = await Appointment.objects.filter(status="pending").all()

    for apt in pending_appointments:
        if apt.is_expired():
            try:
                apt.status = "no_show"
                apt.cancelled_at = now
                apt.cancel_reason = "预约超时未到店，自动记为爽约"
                await apt.update()

                no_show = NoShowRecord(
                    phone=apt.phone,
                    appointment=apt,
                    store=apt.store,
                    appointment_date=apt.appointment_date,
                    time_slot=apt.time_slot,
                    room_type=apt.room_type,
                    remark="系统自动检测超时"
                )
                await no_show.save()
            except Exception:
                pass


class AppointmentListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        status = req.get_param("status")
        phone = req.get_param("phone")
        appointment_date = req.get_param("appointment_date")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        query = Appointment.objects.select_related("store")

        if store_id is not None:
            query = query.filter(store__id=store_id)
        if status:
            statuses = status.split(",")
            query = query.filter(status__in=statuses)
        if phone:
            query = query.filter(phone=phone)
        if appointment_date:
            query = query.filter(appointment_date=appointment_date)

        total = await query.count()
        records = await query.order_by("-created_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for r in records:
            data = r.dict()
            if r.store:
                data["store_name"] = r.store.name
            data["room_type_text"] = r.get_room_type_text()
            data["status_text"] = r.get_status_text()
            data["is_expired"] = r.is_expired()
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

        appointment_date = (data.get("appointment_date") or "").strip()
        if not appointment_date:
            raise falcon.HTTPBadRequest(title="参数错误", description="预约日期不能为空")
        try:
            apt_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        except ValueError:
            raise falcon.HTTPBadRequest(title="参数错误", description="预约日期格式错误，应为YYYY-MM-DD")

        today = date.today()
        max_future = today + timedelta(days=MAX_FUTURE_DAYS)
        if apt_date < today:
            raise falcon.HTTPBadRequest(title="参数错误", description="不能预约过去的日期")
        if apt_date > max_future:
            raise falcon.HTTPBadRequest(title="参数错误", description=f"最多只能预约未来{MAX_FUTURE_DAYS}天")

        time_slot = (data.get("time_slot") or "").strip()
        if not time_slot:
            raise falcon.HTTPBadRequest(title="参数错误", description="预约时段不能为空")
        if time_slot not in DEFAULT_TIME_SLOTS:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的预约时段")

        room_type = (data.get("room_type") or "standard").strip()
        if room_type not in ROOM_TYPES:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的试衣间类型")

        store = None
        store_id = data.get("store_id")
        if store_id:
            try:
                store = await Store.objects.get(id=store_id)
            except Exception:
                raise falcon.HTTPBadRequest(title="参数错误", description="门店不存在")

        penalty_info = await get_no_show_count_with_penalty(phone)
        penalty = penalty_info["penalty"]
        no_show_count = penalty_info["no_show_count"]

        if not penalty["can_appointment"]:
            raise falcon.HTTPBadRequest(
                title="预约失败",
                description=f"您近30天内爽约次数已达{no_show_count}次，"
                           f"当前处于【{penalty['name']}】状态，暂无法预约。"
                           f"请联系工作人员处理或等待{penalty.get('ban_days', 30)}天后自动解封。"
            )

        max_allowed_days = penalty["max_future_days"]
        today = date.today()
        max_future = today + timedelta(days=max_allowed_days)
        if apt_date < today:
            raise falcon.HTTPBadRequest(title="参数错误", description="不能预约过去的日期")
        if apt_date > max_future:
            raise falcon.HTTPBadRequest(
                title="参数错误",
                description=f"由于您的爽约记录，当前最多只能预约未来{max_allowed_days}天"
            )

        exist_pending = await Appointment.objects.filter(
            phone=phone,
            status="pending"
        ).exists()
        if exist_pending:
            raise falcon.HTTPBadRequest(title="预约失败", description="该手机号已有待核销的预约")

        exist_active_queue = await QueueRecord.objects.filter(
            phone=phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active_queue:
            raise falcon.HTTPBadRequest(title="预约失败", description="该手机号已在排队中")

        capacity = await get_slot_capacity(store_id, room_type, time_slot)
        booked_count = await get_slot_booked_count(store_id, appointment_date, room_type, time_slot)
        if booked_count >= capacity:
            raise falcon.HTTPBadRequest(title="预约失败", description="该时段预约已满，请选择其他时段")

        appointment_no = await generate_appointment_no()

        appointment = Appointment(
            appointment_no=appointment_no,
            store=store,
            customer_name=data.get("customer_name"),
            phone=phone,
            room_type=room_type,
            appointment_date=appointment_date,
            time_slot=time_slot,
            status="pending"
        )
        await appointment.save()

        result = appointment.dict()
        if store:
            result["store_name"] = store.name
        result["room_type_text"] = appointment.get_room_type_text()
        result["status_text"] = appointment.get_status_text()
        result["no_show_count"] = no_show_count
        result["penalty"] = penalty
        if no_show_count > 0:
            result["warning"] = (
                f"您近30天内爽约{no_show_count}次，当前处于【{penalty['name']}】状态。"
                f"再爽约{penalty_info['remain_times']}次将被封禁。"
            )

        resp.media = {"code": 0, "message": "预约成功", "data": result}


class AppointmentDetailResource:
    async def on_get(self, req, resp, appointment_id):
        try:
            apt = await Appointment.objects.select_related("store").get(id=appointment_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="预约记录不存在")

        data = apt.dict()
        if apt.store:
            data["store_name"] = apt.store.name
        data["room_type_text"] = apt.get_room_type_text()
        data["status_text"] = apt.get_status_text()
        data["is_expired"] = apt.is_expired()

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_delete(self, req, resp, appointment_id):
        try:
            apt = await Appointment.objects.get(id=appointment_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="预约记录不存在")

        if apt.status in ["confirmed"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="该预约已核销，无法取消")
        if apt.status in ["cancelled", "no_show", "expired"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="该预约已取消/过期")

        apt.status = "cancelled"
        apt.cancelled_at = datetime.now()
        try:
            data = await req.get_media()
            apt.cancel_reason = (data or {}).get("cancel_reason", "用户主动取消")
        except Exception:
            apt.cancel_reason = "用户主动取消"
        await apt.update()

        resp.media = {"code": 0, "message": "取消预约成功"}


class AppointmentConfirmResource:
    async def on_post(self, req, resp, appointment_id):
        try:
            apt = await Appointment.objects.select_related("store").get(id=appointment_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="预约记录不存在")

        if apt.status != "pending":
            raise falcon.HTTPBadRequest(
                title="核销失败",
                description=f"当前状态：{apt.get_status_text()}，无法核销"
            )

        if apt.is_expired():
            apt.status = "no_show"
            apt.cancelled_at = datetime.now()
            apt.cancel_reason = "核销时检测到已超时，记为爽约"
            await apt.update()

            no_show = NoShowRecord(
                phone=apt.phone,
                appointment=apt,
                store=apt.store,
                appointment_date=apt.appointment_date,
                time_slot=apt.time_slot,
                room_type=apt.room_type,
                remark="核销时检测超时"
            )
            await no_show.save()
            raise falcon.HTTPBadRequest(title="核销失败", description="预约已超时，已记为爽约")

        exist_active = await QueueRecord.objects.filter(
            phone=apt.phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise falcon.HTTPBadRequest(title="核销失败", description="该手机号已有进行中的排队")

        ticket_number = await generate_ticket_number(apt.store.id if apt.store else None)

        queue_record = QueueRecord(
            ticket_number=ticket_number,
            store=apt.store,
            customer_name=apt.customer_name,
            phone=apt.phone,
            status="waiting",
            source="appointment",
            appointment_id=apt.id,
            remark=f"预约核销转排队，预约号：{apt.appointment_no}"
        )
        await queue_record.save()

        apt.status = "confirmed"
        apt.confirmed_at = datetime.now()
        apt.queue_record_id = queue_record.id
        await apt.update()

        result = apt.dict()
        if apt.store:
            result["store_name"] = apt.store.name
        result["room_type_text"] = apt.get_room_type_text()
        result["status_text"] = apt.get_status_text()
        result["queue_record"] = {
            "id": queue_record.id,
            "ticket_number": queue_record.ticket_number,
            "status_text": QUEUE_STATUS.get(queue_record.status, queue_record.status)
        }

        resp.media = {"code": 0, "message": "核销成功，已转入排队", "data": result}


class AppointmentSlotsResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        appointment_date = req.get_param("appointment_date") or date.today().strftime("%Y-%m-%d")
        room_type = req.get_param("room_type") or "standard"

        if room_type not in ROOM_TYPES:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的试衣间类型")

        result = []
        for slot in DEFAULT_TIME_SLOTS:
            capacity = await get_slot_capacity(store_id, room_type, slot)
            booked_count = await get_slot_booked_count(store_id, appointment_date, room_type, slot)
            available = max(0, capacity - booked_count)

            slot_start_str = slot.split("-")[0]
            slot_dt = datetime.strptime(f"{appointment_date} {slot_start_str}", "%Y-%m-%d %H:%M")
            is_past = slot_dt < datetime.now()

            result.append({
                "time_slot": slot,
                "capacity": capacity,
                "booked_count": booked_count,
                "available": available,
                "is_full": booked_count >= capacity,
                "is_past": is_past
            })

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class AppointmentDateRangeResource:
    async def on_get(self, req, resp):
        today = date.today()
        dates = []
        for i in range(MAX_FUTURE_DAYS + 1):
            d = today + timedelta(days=i)
            weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            dates.append({
                "date": d.strftime("%Y-%m-%d"),
                "weekday": weekday_map[d.weekday()],
                "is_today": i == 0
            })
        resp.media = {"code": 0, "message": "获取成功", "data": dates}


class AppointmentStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in APPOINTMENT_STATUS.items()]
        }


class AppointmentCheckNoShowResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        result = await get_no_show_count_with_penalty(phone)
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class AppointmentProcessExpiredResource:
    async def on_post(self, req, resp):
        await process_expired_appointments()
        resp.media = {"code": 0, "message": "过期预约处理完成"}


class AppointmentSlotConfigResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        room_type = req.get_param("room_type")

        query = AppointmentSlotConfig.objects.select_related("store")
        if store_id is not None:
            query = query.filter(store__id=store_id)
        if room_type:
            query = query.filter(room_type=room_type)

        configs = await query.order_by("time_slot").all()
        result = []
        for c in configs:
            data = c.dict()
            if c.store:
                data["store_name"] = c.store.name
            data["room_type_text"] = ROOM_TYPES.get(c.room_type, c.room_type)
            result.append(data)

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        store_id = data.get("store_id")
        room_type = (data.get("room_type") or "standard").strip()
        time_slot = (data.get("time_slot") or "").strip()
        capacity = data.get("capacity") or 5
        is_active = data.get("is_active", True)

        if room_type not in ROOM_TYPES:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的试衣间类型")
        if time_slot not in DEFAULT_TIME_SLOTS:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的时段")
        if not isinstance(capacity, int) or capacity <= 0 or capacity > 100:
            raise falcon.HTTPBadRequest(title="参数错误", description="容量必须为1-100的整数")

        store = None
        if store_id:
            try:
                store = await Store.objects.get(id=store_id)
            except Exception:
                raise falcon.HTTPBadRequest(title="参数错误", description="门店不存在")

        exist_config = await AppointmentSlotConfig.objects.filter(
            store__id=store_id if store_id else None if store_id == 0 else None,
            room_type=room_type,
            time_slot=time_slot
        ).first()

        if exist_config:
            exist_config.capacity = capacity
            exist_config.is_active = is_active
            exist_config.updated_at = datetime.now()
            await exist_config.update()
            result = exist_config.dict()
        else:
            config = AppointmentSlotConfig(
                store=store,
                room_type=room_type,
                time_slot=time_slot,
                capacity=capacity,
                is_active=is_active
            )
            await config.save()
            result = config.dict()

        resp.media = {"code": 0, "message": "保存成功", "data": result}
