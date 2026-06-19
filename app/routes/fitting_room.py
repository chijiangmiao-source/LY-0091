import falcon
import json
from datetime import datetime
from app.models import FittingRoom, Store, ROOM_STATUS, ROOM_TYPES


class FittingRoomListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        status = req.get_param("status")

        query = FittingRoom.objects.select_related("store")
        if store_id is not None:
            query = query.filter(store__id=store_id)
        if status:
            query = query.filter(status=status)

        rooms = await query.order_by("room_number").all()
        result = []
        for room in rooms:
            data = room.dict()
            if room.store:
                data["store_name"] = room.store.name
                data["store_floor"] = room.store.floor
            data["status_text"] = ROOM_STATUS.get(room.status, room.status)
            data["room_type_text"] = ROOM_TYPES.get(room.room_type, room.room_type)
            result.append(data)

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        if not data.get("room_number"):
            raise falcon.HTTPBadRequest(title="参数错误", description="房间编号不能为空")

        exist = await FittingRoom.objects.filter(room_number=data.get("room_number")).exists()
        if exist:
            raise falcon.HTTPBadRequest(title="创建失败", description="房间编号已存在")

        store = None
        if data.get("store_id"):
            try:
                store = await Store.objects.get(id=data.get("store_id"))
            except Exception:
                raise falcon.HTTPBadRequest(title="参数错误", description="门店不存在")

        room = FittingRoom(
            room_number=data.get("room_number"),
            store=store,
            room_type=data.get("room_type", "standard"),
            status=data.get("status", "available"),
            last_clean_time=datetime.now(),
            remark=data.get("remark")
        )
        await room.save()

        resp.media = {"code": 0, "message": "创建成功", "data": room.dict()}


class FittingRoomDetailResource:
    async def on_get(self, req, resp, room_id):
        try:
            room = await FittingRoom.objects.select_related("store").get(id=room_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="试衣间不存在")

        data = room.dict()
        if room.store:
            data["store_name"] = room.store.name
            data["store_floor"] = room.store.floor
        data["status_text"] = ROOM_STATUS.get(room.status, room.status)
        data["room_type_text"] = ROOM_TYPES.get(room.room_type, room.room_type)

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_put(self, req, resp, room_id):
        try:
            room = await FittingRoom.objects.get(id=room_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="试衣间不存在")

        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        if "room_number" in data and data["room_number"]:
            if data["room_number"] != room.room_number:
                exist = await FittingRoom.objects.filter(room_number=data["room_number"]).exists()
                if exist:
                    raise falcon.HTTPBadRequest(title="更新失败", description="房间编号已存在")
            room.room_number = data["room_number"]

        if "store_id" in data:
            if data.get("store_id"):
                try:
                    store = await Store.objects.get(id=data.get("store_id"))
                    room.store = store
                except Exception:
                    raise falcon.HTTPBadRequest(title="参数错误", description="门店不存在")
            else:
                room.store = None

        if "room_type" in data and data["room_type"]:
            room.room_type = data["room_type"]
        if "status" in data and data["status"]:
            room.status = data["status"]
        if "remark" in data:
            room.remark = data.get("remark")

        await room.update()
        resp.media = {"code": 0, "message": "更新成功", "data": room.dict()}

    async def on_delete(self, req, resp, room_id):
        try:
            room = await FittingRoom.objects.get(id=room_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="试衣间不存在")

        if room.status in ["occupied", "sealed"]:
            raise falcon.HTTPBadRequest(title="删除失败", description=f"试衣间当前状态为{ROOM_STATUS.get(room.status)}，无法删除")

        await room.delete()
        resp.media = {"code": 0, "message": "删除成功"}


class FittingRoomCleanResource:
    async def on_post(self, req, resp, room_id):
        try:
            room = await FittingRoom.objects.get(id=room_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="试衣间不存在")

        if room.status not in ["cleaning"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="当前状态无需清理")

        room.status = "available"
        room.last_clean_time = datetime.now()
        await room.update()

        resp.media = {"code": 0, "message": "清理完成，试衣间已恢复使用"}


class FittingRoomStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "status_options": [{"value": k, "label": v} for k, v in ROOM_STATUS.items()],
                "type_options": [{"value": k, "label": v} for k, v in ROOM_TYPES.items()]
            }
        }
