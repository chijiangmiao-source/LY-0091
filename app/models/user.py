import ormar
from datetime import datetime
from app.config import MainMeta
import bcrypt


class User(ormar.Model):
    class Meta(MainMeta):
        tablename = "users"

    id: int = ormar.Integer(primary_key=True)
    username: str = ormar.String(max_length=50, unique=True)
    password_hash: str = ormar.String(max_length=255)
    real_name: str = ormar.String(max_length=50)
    role: str = ormar.String(max_length=20, default="staff")
    created_at: datetime = ormar.DateTime(default=datetime.now)

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))
