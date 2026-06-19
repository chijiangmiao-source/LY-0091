import ormar
from datetime import datetime
from typing import Optional
from app.config import MainMeta
from app.models.fitting_room import FittingRoom
from app.models.queue_record import QueueRecord
from app.models.user import User


LOST_ITEM_STATUS = {
    "registered": "已登记",
    "sealed": "已封存",
    "claimed": "已认领",
    "disposed": "已处理"
}


class LostItem(ormar.Model):
    class Meta(MainMeta):
        tablename = "lost_items"

    id: int = ormar.Integer(primary_key=True)
    item_name: str = ormar.String(max_length=100)
    item_description: str = ormar.Text()
    item_category: str = ormar.String(max_length=50, nullable=True)
    fitting_room: Optional[FittingRoom] = ormar.ForeignKey(FittingRoom, related_name="lost_items", nullable=True)
    queue_record: Optional[QueueRecord] = ormar.ForeignKey(QueueRecord, related_name="lost_items", nullable=True)
    register_user: Optional[User] = ormar.ForeignKey(User, related_name="registered_items", nullable=True)
    register_time: datetime = ormar.DateTime(default=datetime.now)
    seal_location: str = ormar.String(max_length=200, nullable=True)
    seal_time: Optional[datetime] = ormar.DateTime(nullable=True)
    seal_user: Optional[User] = ormar.ForeignKey(User, related_name="sealed_items", nullable=True)
    status: str = ormar.String(max_length=20, default="registered")
    claimant_name: str = ormar.String(max_length=50, nullable=True)
    claimant_phone: str = ormar.String(max_length=20, nullable=True)
    claimant_id_number: str = ormar.String(max_length=50, nullable=True)
    claim_time: Optional[datetime] = ormar.DateTime(nullable=True)
    claim_user: Optional[User] = ormar.ForeignKey(User, related_name="claimed_items", nullable=True)
    claim_verified: bool = ormar.Boolean(default=False)
    remark: str = ormar.String(max_length=500, nullable=True)
