import ormar
from datetime import datetime, timedelta
from typing import Optional
from app.config import MainMeta
from app.models.store import Store
from app.models.fitting_room import ROOM_TYPES
from app.models.queue_record import QUEUE_SOURCE
from app.models.user import User


TRANSFER_STATUS = {
    "pending": "待确认",
    "customer_confirmed": "顾客已确认",
    "customer_rejected": "顾客已拒绝",
    "target_accepted": "目标门店已接受",
    "target_rejected": "目标门店已拒绝",
    "completed": "转单完成",
    "cancelled": "已取消",
    "failed": "转单失败",
}

TRANSFER_REASON = {
    "busy": "试衣间繁忙",
    "temp_closed": "门店临时停用",
    "room_unavailable": "指定房型不可用",
    "equipment_failure": "设备故障",
    "cleaning": "清洁中",
    "customer_request": "顾客主动要求",
    "staff_suggest": "工作人员推荐",
    "other": "其他原因",
}

TRANSFER_SOURCE_TYPE = {
    "queue": "排队记录",
    "appointment": "预约记录",
}

CUSTOMER_CONFIRM_STATUS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "rejected": "已拒绝",
    "timeout": "确认超时",
}


class StoreTransfer(ormar.Model):
    class Meta(MainMeta):
        tablename = "store_transfers"

    id: int = ormar.Integer(primary_key=True)
    transfer_no: str = ormar.String(max_length=30, unique=True)

    source_type: str = ormar.String(max_length=20, default="queue")
    source_queue_id: Optional[int] = ormar.Integer(nullable=True)
    source_appointment_id: Optional[int] = ormar.Integer(nullable=True)
    original_source: str = ormar.String(max_length=20, nullable=True)
    original_ticket_no: str = ormar.String(max_length=50, nullable=True)

    source_store: Optional[Store] = ormar.ForeignKey(
        Store, related_name="outgoing_transfers", nullable=True
    )
    target_store: Optional[Store] = ormar.ForeignKey(
        Store, related_name="incoming_transfers", nullable=True
    )

    customer_name: str = ormar.String(max_length=50, nullable=True)
    phone: str = ormar.String(max_length=20, index=True)
    room_type: str = ormar.String(max_length=20, default="standard")

    transfer_reason: str = ormar.String(max_length=50, default="other")
    transfer_reason_detail: str = ormar.String(max_length=500, nullable=True)

    status: str = ormar.String(max_length=30, default="pending")
    customer_confirm_status: str = ormar.String(max_length=20, default="pending")
    customer_confirm_time: Optional[datetime] = ormar.DateTime(nullable=True)
    customer_confirm_note: str = ormar.String(max_length=500, nullable=True)

    target_store_accepted: bool = ormar.Boolean(default=False)
    target_store_accept_time: Optional[datetime] = ormar.DateTime(nullable=True)
    target_store_reject_reason: str = ormar.String(max_length=500, nullable=True)

    operator: Optional[User] = ormar.ForeignKey(
        User, related_name="transfer_ops", nullable=True
    )
    operator_name: str = ormar.String(max_length=50, nullable=True)

    new_queue_id: Optional[int] = ormar.Integer(nullable=True)
    new_appointment_id: Optional[int] = ormar.Integer(nullable=True)

    recommend_score: float = ormar.Float(default=0.0)
    floor_distance: int = ormar.Integer(default=0)
    source_load_level: str = ormar.String(max_length=20, nullable=True)
    target_load_level: str = ormar.String(max_length=20, nullable=True)

    priority_boost: bool = ormar.Boolean(default=False)
    priority_note: str = ormar.String(max_length=200, nullable=True)

    created_at: datetime = ormar.DateTime(default=datetime.now)
    updated_at: datetime = ormar.DateTime(default=datetime.now)
    completed_at: Optional[datetime] = ormar.DateTime(nullable=True)
    cancelled_at: Optional[datetime] = ormar.DateTime(nullable=True)
    remark: str = ormar.String(max_length=500, nullable=True)

    def get_status_text(self) -> str:
        return TRANSFER_STATUS.get(self.status, self.status)

    def get_reason_text(self) -> str:
        return TRANSFER_REASON.get(self.transfer_reason, self.transfer_reason)

    def get_source_type_text(self) -> str:
        return TRANSFER_SOURCE_TYPE.get(self.source_type, self.source_type)

    def get_room_type_text(self) -> str:
        return ROOM_TYPES.get(self.room_type, self.room_type)

    def get_customer_confirm_text(self) -> str:
        return CUSTOMER_CONFIRM_STATUS.get(self.customer_confirm_status, self.customer_confirm_status)


class TransferLostItemLink(ormar.Model):
    class Meta(MainMeta):
        tablename = "transfer_lost_item_links"

    id: int = ormar.Integer(primary_key=True)
    transfer: Optional[StoreTransfer] = ormar.ForeignKey(
        StoreTransfer, related_name="lost_item_links", nullable=True
    )
    lost_item_id: int = ormar.Integer()
    original_store: Optional[Store] = ormar.ForeignKey(
        Store, related_name="original_lost_links", nullable=True
    )
    current_store: Optional[Store] = ormar.ForeignKey(
        Store, related_name="current_lost_links", nullable=True
    )
    tracking_status: str = ormar.String(max_length=30, default="transiting")
    handover_note: str = ormar.String(max_length=500, nullable=True)
    handover_by: Optional[User] = ormar.ForeignKey(
        User, related_name="lost_item_handovers", nullable=True
    )
    handover_time: Optional[datetime] = ormar.DateTime(nullable=True)
    received_by: Optional[User] = ormar.ForeignKey(
        User, related_name="lost_item_receives", nullable=True
    )
    received_time: Optional[datetime] = ormar.DateTime(nullable=True)
    created_at: datetime = ormar.DateTime(default=datetime.now)


TRANSFER_ITEM_TRACKING_STATUS = {
    "transiting": "转运中",
    "at_target": "已送达目标门店",
    "claimed": "顾客已领取",
    "returned": "已退回源门店",
    "disposed": "已处理",
}


def calc_floor_distance(source_floor: int, target_floor: int) -> int:
    return abs(source_floor - target_floor)


def classify_load_level(waiting_count: int, room_count: int) -> str:
    if room_count <= 0:
        return "unknown"
    ratio = waiting_count / room_count
    if ratio <= 0.5:
        return "low"
    elif ratio <= 1.5:
        return "medium"
    elif ratio <= 3.0:
        return "high"
    else:
        return "critical"


LOAD_LEVEL_TEXT = {
    "low": "空闲",
    "medium": "正常",
    "high": "繁忙",
    "critical": "极忙",
    "unknown": "未知",
}


async def generate_transfer_no() -> str:
    now = datetime.now()
    date_prefix = now.strftime("%Y%m%d")
    prefix = f"T{date_prefix}"

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    today_count = await StoreTransfer.objects.filter(
        created_at__gte=today_start,
        created_at__lt=today_end
    ).count()

    sequence = today_count + 1
    suffix = f"{sequence:04d}"
    transfer_no = f"{prefix}{suffix}"

    exists = await StoreTransfer.objects.filter(transfer_no=transfer_no).exists()
    if exists:
        max_record = await StoreTransfer.objects.filter(
            transfer_no__startswith=prefix
        ).order_by("-transfer_no").first()
        if max_record:
            last_seq = int(max_record.transfer_no[-4:])
            sequence = last_seq + 1
            suffix = f"{sequence:04d}"
            transfer_no = f"{prefix}{suffix}"

    return transfer_no
