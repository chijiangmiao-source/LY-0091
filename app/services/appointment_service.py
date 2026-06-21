from datetime import datetime, timedelta, date

from app.services.base import BaseService
from app.services.member_service import member_service
from app.services.queue_service import queue_service
from app.exceptions import (
    NotFoundError, StateConflictError, ValidationError,
    BlacklistBlockedError, BlacklistGrayError, PenaltyBlockedError
)
from app.models import (
    Appointment, NoShowRecord, AppointmentSlotConfig, Store,
    APPOINTMENT_STATUS, NO_SHOW_THRESHOLD, APPOINTMENT_TIMEOUT_MINUTES,
    MAX_FUTURE_DAYS, DEFAULT_TIME_SLOTS, ROOM_TYPES,
    QueueRecord, QUEUE_SOURCE, QUEUE_STATUS,
    get_no_show_count_with_penalty
)


class AppointmentService(BaseService):

    async def generate_appointment_no(self) -> str:
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

    async def get_slot_capacity(self, store_id, room_type: str, time_slot: str) -> int:
        config = await AppointmentSlotConfig.objects.filter(
            store__id=store_id if store_id else None,
            room_type=room_type,
            time_slot=time_slot,
            is_active=True
        ).first()
        return config.capacity if config else 5

    async def get_slot_booked_count(
        self,
        store_id,
        appointment_date: str,
        room_type: str,
        time_slot: str
    ) -> int:
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

    async def process_expired_appointments(self):
        now = datetime.now()
        pending_appointments = await Appointment.objects.filter(status="pending").all()

        count = 0
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

                    await member_service.record_behavior(
                        phone=apt.phone,
                        behavior_type="no_show",
                        related_id=apt.id,
                        detail=f"预约爽约：{apt.appointment_no}"
                    )
                    count += 1
                except Exception as e:
                    self.log.error("process_expired", str(e), exc_info=True, appointment_no=apt.appointment_no)

        self.log.info("process_expired_appointments", f"processed={count}")
        return count

    async def create_appointment(
        self,
        phone: str,
        appointment_date: str,
        time_slot: str,
        room_type: str = "standard",
        customer_name: str = None,
        store_id: int = None,
        verify_code: str = None
    ) -> dict:
        if not phone:
            raise ValidationError("手机号不能为空")
        if not appointment_date:
            raise ValidationError("预约日期不能为空")
        try:
            apt_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError("预约日期格式错误，应为YYYY-MM-DD")

        today = date.today()
        max_future_default = today + timedelta(days=MAX_FUTURE_DAYS)
        if apt_date < today:
            raise ValidationError("不能预约过去的日期")
        if apt_date > max_future_default:
            raise ValidationError(f"最多只能预约未来{MAX_FUTURE_DAYS}天")

        if not time_slot:
            raise ValidationError("预约时段不能为空")
        if time_slot not in DEFAULT_TIME_SLOTS:
            raise ValidationError("无效的预约时段")

        if room_type not in ROOM_TYPES:
            raise ValidationError("无效的试衣间类型")

        store = None
        if store_id:
            try:
                store = await Store.objects.get(id=store_id)
            except Exception:
                raise ValidationError("门店不存在")

        await member_service.validate_blacklist_for_scene(
            phone=phone,
            scene="appointment",
            verify_code=verify_code,
            scene_label="预约"
        )

        penalty_info = await get_no_show_count_with_penalty(phone)
        penalty = penalty_info["penalty"]
        no_show_count = penalty_info["no_show_count"]

        if not penalty["can_appointment"]:
            raise PenaltyBlockedError(
                description=f"您近30天内爽约次数已达{no_show_count}次，"
                           f"当前处于【{penalty['name']}】状态，暂无法预约。"
                           f"请联系工作人员处理或等待{penalty.get('ban_days', 30)}天后自动解封。",
                scene="预约"
            )

        max_allowed_days = penalty["max_future_days"]
        max_future = today + timedelta(days=max_allowed_days)
        if apt_date > max_future:
            raise ValidationError(
                f"由于您的爽约记录，当前最多只能预约未来{max_allowed_days}天"
            )

        exist_pending = await Appointment.objects.filter(
            phone=phone,
            status="pending"
        ).exists()
        if exist_pending:
            raise StateConflictError("该手机号已有待核销的预约", title="预约失败")

        exist_active_queue = await QueueRecord.objects.filter(
            phone=phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active_queue:
            raise StateConflictError("该手机号已在排队中", title="预约失败")

        capacity = await self.get_slot_capacity(store_id, room_type, time_slot)
        booked_count = await self.get_slot_booked_count(store_id, appointment_date, room_type, time_slot)
        if booked_count >= capacity:
            raise StateConflictError("该时段预约已满，请选择其他时段", title="预约失败")

        appointment_no = await self.generate_appointment_no()

        appointment = Appointment(
            appointment_no=appointment_no,
            store=store,
            customer_name=customer_name,
            phone=phone,
            room_type=room_type,
            appointment_date=appointment_date,
            time_slot=time_slot,
            status="pending"
        )
        await appointment.save()

        await member_service.get_or_create_member(phone, customer_name)
        await member_service.record_behavior(
            phone=phone,
            behavior_type="appointment",
            related_id=appointment.id,
            store_name=store.name if store else None,
            detail=f"预约号：{appointment_no}，日期：{appointment_date}，时段：{time_slot}"
        )

        self.log.info("create_appointment", f"no={appointment_no}, phone={phone}")

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

        return result

    async def get_appointment_detail(self, appointment_id: int) -> dict:
        try:
            apt = await Appointment.objects.select_related("store").get(id=appointment_id)
        except Exception:
            raise NotFoundError("预约记录不存在")

        data = apt.dict()
        if apt.store:
            data["store_name"] = apt.store.name
        data["room_type_text"] = apt.get_room_type_text()
        data["status_text"] = apt.get_status_text()
        data["is_expired"] = apt.is_expired()
        return data

    async def cancel_appointment(self, appointment_id: int, cancel_reason: str = None) -> None:
        try:
            apt = await Appointment.objects.get(id=appointment_id)
        except Exception:
            raise NotFoundError("预约记录不存在")

        if apt.status in ["confirmed"]:
            raise StateConflictError("该预约已核销，无法取消", title="操作失败")
        if apt.status in ["cancelled", "no_show", "expired"]:
            raise StateConflictError("该预约已取消/过期", title="操作失败")

        apt.status = "cancelled"
        apt.cancelled_at = datetime.now()
        apt.cancel_reason = cancel_reason or "用户主动取消"
        await apt.update()

        self.log.info("cancel_appointment", f"no={apt.appointment_no}")

    async def confirm_appointment(self, appointment_id: int) -> dict:
        try:
            apt = await Appointment.objects.select_related("store").get(id=appointment_id)
        except Exception:
            raise NotFoundError("预约记录不存在")

        if apt.status != "pending":
            raise StateConflictError(
                f"当前状态：{apt.get_status_text()}，无法核销",
                title="核销失败"
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

            await member_service.record_behavior(
                phone=apt.phone,
                behavior_type="no_show",
                related_id=apt.id,
                detail=f"预约核销超时：{apt.appointment_no}"
            )
            raise StateConflictError("预约已超时，已记为爽约", title="核销失败")

        exist_active = await QueueRecord.objects.filter(
            phone=apt.phone,
            status__in=["waiting", "called", "entered"]
        ).exists()
        if exist_active:
            raise StateConflictError("该手机号已有进行中的排队", title="核销失败")

        ticket_number = await queue_service.generate_ticket_number(
            apt.store.id if apt.store else None
        )

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

        self.log.info("confirm_appointment", f"no={apt.appointment_no}, ticket={ticket_number}")

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

        return result

    async def get_available_slots(
        self,
        store_id: int = None,
        appointment_date: str = None,
        room_type: str = "standard"
    ) -> list:
        if room_type not in ROOM_TYPES:
            raise ValidationError("无效的试衣间类型")

        appointment_date = appointment_date or date.today().strftime("%Y-%m-%d")

        result = []
        for slot in DEFAULT_TIME_SLOTS:
            capacity = await self.get_slot_capacity(store_id, room_type, slot)
            booked_count = await self.get_slot_booked_count(store_id, appointment_date, room_type, slot)
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

        return result

    async def get_date_range(self) -> list:
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
        return dates

    async def save_slot_config(
        self,
        store_id: int = None,
        room_type: str = "standard",
        time_slot: str = None,
        capacity: int = 5,
        is_active: bool = True
    ) -> dict:
        if room_type not in ROOM_TYPES:
            raise ValidationError("无效的试衣间类型")
        if time_slot not in DEFAULT_TIME_SLOTS:
            raise ValidationError("无效的时段")
        if not isinstance(capacity, int) or capacity <= 0 or capacity > 100:
            raise ValidationError("容量必须为1-100的整数")

        store = None
        if store_id:
            try:
                store = await Store.objects.get(id=store_id)
            except Exception:
                raise ValidationError("门店不存在")

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

        self.log.info("save_slot_config", f"store={store_id}, slot={time_slot}, capacity={capacity}")
        return result

    async def list_slot_configs(
        self,
        store_id: int = None,
        room_type: str = None
    ) -> list:
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

        return result

    async def list_appointments(
        self,
        store_id: int = None,
        status: str = None,
        phone: str = None,
        appointment_date: str = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
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

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": result
        }


appointment_service = AppointmentService()
