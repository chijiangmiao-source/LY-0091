import ormar
from datetime import datetime, timedelta
from typing import Optional
from app.config import MainMeta
from app.models.store import Store
from app.models.fitting_room import ROOM_TYPES


APPOINTMENT_STATUS = {
    "pending": "待核销",
    "confirmed": "已核销",
    "cancelled": "已取消",
    "no_show": "爽约",
    "expired": "已过期"
}

NO_SHOW_THRESHOLD = 3
APPOINTMENT_TIMEOUT_MINUTES = 15
MAX_FUTURE_DAYS = 7

NO_SHOW_PENALTY_LEVELS = {
    0: {"level": 0, "name": "正常", "can_appointment": True, "can_onsite": True, "max_future_days": 7, "need_verify": False},
    1: {"level": 1, "name": "一级警告", "can_appointment": True, "can_onsite": True, "max_future_days": 5, "need_verify": False},
    2: {"level": 2, "name": "二级限制", "can_appointment": True, "can_onsite": True, "max_future_days": 3, "need_verify": False},
    3: {"level": 3, "name": "三级封禁", "can_appointment": False, "can_onsite": False, "max_future_days": 0, "need_verify": False, "ban_days": 30},
}

NO_SHOW_RECORD_EXPIRE_DAYS = 90


class Appointment(ormar.Model):
    class Meta(MainMeta):
        tablename = "appointments"

    id: int = ormar.Integer(primary_key=True)
    appointment_no: str = ormar.String(max_length=30, unique=True)
    store: Optional[Store] = ormar.ForeignKey(Store, related_name="appointments", nullable=True)
    customer_name: str = ormar.String(max_length=50, nullable=True)
    phone: str = ormar.String(max_length=20)
    room_type: str = ormar.String(max_length=20, default="standard")
    appointment_date: str = ormar.String(max_length=10)
    time_slot: str = ormar.String(max_length=20)
    status: str = ormar.String(max_length=20, default="pending")
    created_at: datetime = ormar.DateTime(default=datetime.now)
    confirmed_at: Optional[datetime] = ormar.DateTime(nullable=True)
    cancelled_at: Optional[datetime] = ormar.DateTime(nullable=True)
    cancel_reason: str = ormar.String(max_length=200, nullable=True)
    queue_record_id: Optional[int] = ormar.Integer(nullable=True)
    remark: str = ormar.String(max_length=500, nullable=True)

    def is_active(self) -> bool:
        return self.status == "pending"

    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        now = datetime.now()
        slot_start = self._parse_slot_start()
        if slot_start:
            expiry_time = slot_start + timedelta(minutes=APPOINTMENT_TIMEOUT_MINUTES)
            return now > expiry_time
        return False

    def _parse_slot_start(self) -> Optional[datetime]:
        try:
            date_part = self.appointment_date
            time_part = self.time_slot.split("-")[0]
            return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
        except Exception:
            return None

    def get_room_type_text(self) -> str:
        return ROOM_TYPES.get(self.room_type, self.room_type)

    def get_status_text(self) -> str:
        return APPOINTMENT_STATUS.get(self.status, self.status)


class NoShowRecord(ormar.Model):
    class Meta(MainMeta):
        tablename = "no_show_records"

    id: int = ormar.Integer(primary_key=True)
    phone: str = ormar.String(max_length=20, index=True)
    appointment: Optional[Appointment] = ormar.ForeignKey(
        Appointment, related_name="no_show_records", nullable=True
    )
    store: Optional[Store] = ormar.ForeignKey(Store, related_name="no_show_records", nullable=True)
    appointment_date: str = ormar.String(max_length=10)
    time_slot: str = ormar.String(max_length=20)
    room_type: str = ormar.String(max_length=20, default="standard")
    recorded_at: datetime = ormar.DateTime(default=datetime.now)
    remark: str = ormar.String(max_length=500, nullable=True)


class AppointmentSlotConfig(ormar.Model):
    class Meta(MainMeta):
        tablename = "appointment_slot_configs"

    id: int = ormar.Integer(primary_key=True)
    store: Optional[Store] = ormar.ForeignKey(Store, related_name="slot_configs", nullable=True)
    room_type: str = ormar.String(max_length=20, default="standard")
    time_slot: str = ormar.String(max_length=20)
    capacity: int = ormar.Integer(default=5)
    is_active: bool = ormar.Boolean(default=True)
    created_at: datetime = ormar.DateTime(default=datetime.now)
    updated_at: datetime = ormar.DateTime(default=datetime.now)


def generate_time_slots(start_hour: int = 9, end_hour: int = 22, duration_minutes: int = 30) -> list:
    slots = []
    current = start_hour * 60
    end = end_hour * 60
    while current + duration_minutes <= end:
        start_h = current // 60
        start_m = current % 60
        end_current = current + duration_minutes
        end_h = end_current // 60
        end_m = end_current % 60
        slots.append(f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}")
        current += duration_minutes
    return slots


DEFAULT_TIME_SLOTS = generate_time_slots()


def get_no_show_penalty(no_show_count: int) -> dict:
    if no_show_count <= 0:
        return NO_SHOW_PENALTY_LEVELS[0].copy()
    elif no_show_count == 1:
        return NO_SHOW_PENALTY_LEVELS[1].copy()
    elif no_show_count == 2:
        return NO_SHOW_PENALTY_LEVELS[2].copy()
    else:
        return NO_SHOW_PENALTY_LEVELS[3].copy()


async def get_no_show_count_with_penalty(phone: str, days: int = 30) -> dict:
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    count = await NoShowRecord.objects.filter(
        phone=phone,
        appointment_date__gte=start_date
    ).count()
    penalty = get_no_show_penalty(count)
    return {
        "phone": phone,
        "no_show_count": count,
        "threshold": NO_SHOW_THRESHOLD,
        "penalty": penalty,
        "is_blocked": not penalty["can_appointment"] or not penalty["can_onsite"],
        "remain_times": max(0, NO_SHOW_THRESHOLD - count)
    }
