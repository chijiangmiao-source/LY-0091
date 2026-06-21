import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import database, metadata, engine
from app.models import (
    User, Store, FittingRoom,
    AppointmentSlotConfig, DEFAULT_TIME_SLOTS, ROOM_TYPES
)


async def init_db():
    await database.connect()

    metadata.create_all(engine)

    admin_exists = await User.objects.filter(username="admin").exists()
    if not admin_exists:
        admin = User(
            username="admin",
            real_name="系统管理员",
            role="admin"
        )
        admin.set_password("admin123")
        await admin.save()
        print("✓ 创建管理员账号: admin / admin123")
    else:
        print("✓ 管理员账号已存在")

    staff_exists = await User.objects.filter(username="staff").exists()
    if not staff_exists:
        staff = User(
            username="staff",
            real_name="普通员工",
            role="staff"
        )
        staff.set_password("staff123")
        await staff.save()
        print("✓ 创建员工账号: staff / staff123")
    else:
        print("✓ 员工账号已存在")

    stores_data = [
        {"name": "优衣库", "floor": 1, "location": "1F-01", "phone": "010-12345678", "manager": "张经理"},
        {"name": "ZARA", "floor": 1, "location": "1F-02", "phone": "010-23456789", "manager": "李经理"},
        {"name": "H&M", "floor": 2, "location": "2F-01", "phone": "010-34567890", "manager": "王经理"},
        {"name": "耐克", "floor": 2, "location": "2F-05", "phone": "010-45678901", "manager": "陈经理"},
        {"name": "阿迪达斯", "floor": 3, "location": "3F-01", "phone": "010-56789012", "manager": "刘经理"},
    ]

    for s_data in stores_data:
        exists = await Store.objects.filter(name=s_data["name"]).exists()
        if not exists:
            store = Store(**s_data)
            await store.save()
            print(f"✓ 创建门店: " + s_data["name"])
        else:
            print(f"✓ 门店已存在: " + s_data["name"])

    stores = await Store.objects.all()
    store_map = {s.name: s for s in await Store.objects.all()}

    rooms_data = [
        {"room_number": "A101", "store_name": "优衣库", "room_type": "standard"},
        {"room_number": "A102", "store_name": "优衣库", "room_type": "standard"},
        {"room_number": "A103", "store_name": "优衣库", "room_type": "large"},
        {"room_number": "B101", "store_name": "ZARA", "room_type": "standard"},
        {"room_number": "B102", "store_name": "ZARA", "room_type": "standard"},
        {"room_number": "C201", "store_name": "H&M", "room_type": "standard"},
        {"room_number": "C202", "store_name": "H&M", "room_type": "family"},
        {"room_number": "D201", "store_name": "耐克", "room_type": "standard"},
        {"room_number": "D202", "store_name": "耐克", "room_type": "large"},
        {"room_number": "E301", "store_name": "阿迪达斯", "room_type": "standard"},
        {"room_number": "E302", "store_name": "阿迪达斯", "room_type": "vip"},
        {"room_number": "PUB-01", "store_name": None, "room_type": "standard"},
        {"room_number": "PUB-02", "store_name": None, "room_type": "family"},
    ]

    for r_data in rooms_data:
        exists = await FittingRoom.objects.filter(room_number=r_data["room_number"]).exists()
        if not exists:
            store = None
            if r_data["store_name"] and r_data["store_name"] in store_map:
                store = store_map[r_data["store_name"]]
            room = FittingRoom(
                room_number=r_data["room_number"],
                store=store,
                room_type=r_data["room_type"],
                status="available"
            )
            await room.save()
            print(f"✓ 创建试衣间: " + r_data["room_number"])
        else:
            print(f"✓ 试衣间已存在: " + r_data["room_number"])

    stores = await Store.objects.all()
    for store in stores:
        for room_type in ROOM_TYPES.keys():
            for slot in DEFAULT_TIME_SLOTS:
                exists = await AppointmentSlotConfig.objects.filter(
                    store__id=store.id,
                    room_type=room_type,
                    time_slot=slot
                ).exists()
                if not exists:
                    config = AppointmentSlotConfig(
                        store=store,
                        room_type=room_type,
                        time_slot=slot,
                        capacity=3,
                        is_active=True
                    )
                    await config.save()
    print(f"✓ 已初始化预约时段配置")

    await database.disconnect()
    print("\n✅ 数据库初始化完成！")
    print("默认管理员账号: admin / admin123")


if __name__ == "__main__":
    asyncio.run(init_db())
