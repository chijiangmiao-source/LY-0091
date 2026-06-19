import ormar
from datetime import datetime
from typing import Optional
from app.config import MainMeta
from app.models.store import Store


ROOM_STATUS = {
    "available": "空闲",
    "occupied": "占用中",
    "cleaning": "待清理",
    "sealed": "已封存(遗留物)"
}

ROOM_TYPES = {
    "standard": "标准间",
    "large": "大码间",
    "family": "家庭间",
    "vip": "VIP间"
}


class FittingRoom(ormar.Model):
    class Meta(MainMeta):
        tablename = "fitting_rooms"

    id: int = ormar.Integer(primary_key=True)
    room_number: str = ormar.String(max_length=20, unique=True)
    store: Optional[Store] = ormar.ForeignKey(Store, related_name="fitting_rooms", nullable=True)
    room_type: str = ormar.String(max_length=20, default="standard")
    status: str = ormar.String(max_length=20, default="available")
    last_clean_time: Optional[datetime] = ormar.DateTime(nullable=True)
    remark: str = ormar.String(max_length=500, nullable=True)
    created_at: datetime = ormar.DateTime(default=datetime.now)

    def is_available(self) -> bool:
        return self.status == "available"

    def is_sealed(self) -> bool:
        return self.status == "sealed"
