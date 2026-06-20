import ormar
from datetime import datetime
from typing import Optional
from app.config import MainMeta
from app.models.store import Store
from app.models.fitting_room import FittingRoom


QUEUE_STATUS = {
    "waiting": "排队中",
    "called": "已叫号",
    "entered": "已入场",
    "left": "已离场",
    "overtime": "已过号",
    "abnormal": "异常"
}


class QueueRecord(ormar.Model):
    class Meta(MainMeta):
        tablename = "queue_records"

    id: int = ormar.Integer(primary_key=True)
    ticket_number: str = ormar.String(max_length=20, unique=True)
    store: Optional[Store] = ormar.ForeignKey(Store, related_name="queue_records", nullable=True)
    fitting_room: Optional[FittingRoom] = ormar.ForeignKey(FittingRoom, related_name="queue_records", nullable=True)
    customer_name: str = ormar.String(max_length=50, nullable=True)
    phone: str = ormar.String(max_length=20)
    queue_time: datetime = ormar.DateTime(default=datetime.now)
    call_time: Optional[datetime] = ormar.DateTime(nullable=True)
    enter_time: Optional[datetime] = ormar.DateTime(nullable=True)
    leave_time: Optional[datetime] = ormar.DateTime(nullable=True)
    status: str = ormar.String(max_length=20, default="waiting")
    is_overtime: bool = ormar.Boolean(default=False)
    is_abnormal: bool = ormar.Boolean(default=False)
    abnormal_reason: str = ormar.String(max_length=500, nullable=True)
    remark: str = ormar.String(max_length=500, nullable=True)

    def is_active(self) -> bool:
        return self.status in ["waiting", "called", "entered"]
