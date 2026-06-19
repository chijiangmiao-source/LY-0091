import ormar
from datetime import datetime
from app.config import MainMeta


class Store(ormar.Model):
    class Meta(MainMeta):
        tablename = "stores"

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)
    floor: int = ormar.Integer()
    location: str = ormar.String(max_length=200)
    phone: str = ormar.String(max_length=20, nullable=True)
    manager: str = ormar.String(max_length=50, nullable=True)
    status: bool = ormar.Boolean(default=True)
    created_at: datetime = ormar.DateTime(default=datetime.now)
