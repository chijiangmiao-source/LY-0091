import os
from dotenv import load_dotenv
import ormar
import databases
import sqlalchemy
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/fitting_room_queue")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
APP_PORT = int(os.getenv("APP_PORT", "8000"))

OVER_TIME_MINUTES = 15

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

engine = create_engine(DATABASE_URL)


class MainMeta(ormar.ModelMeta):
    metadata = metadata
    database = database
