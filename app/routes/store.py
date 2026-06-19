import falcon
import json
from datetime import datetime
from app.models import Store


class StoreListResource:
    async def on_get(self, req, resp):
        floor = req.get_param_as_int("floor")
        status = req.get_param_as_bool("status")

        query = Store.objects
        if floor is not None:
            query = query.filter(floor=floor)
        if status is not None:
            query = query.filter(status=status)

        stores = await query.order_by("-created_at").all()
        result = []
        for store in stores:
            data = store.dict()
            try:
                rooms_count = await store.fitting_rooms.count()
                data["fitting_rooms_count"] = rooms_count
            except Exception:
                data["fitting_rooms_count"] = 0
            result.append(data)

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        required_fields = ["name", "floor"]
        for field in required_fields:
            if not data.get(field):
                raise falcon.HTTPBadRequest(title="参数错误", description=f"{field}不能为空")

        store = Store(
            name=data.get("name"),
            floor=int(data.get("floor")),
            location=data.get("location", ""),
            phone=data.get("phone"),
            manager=data.get("manager"),
            status=data.get("status", True)
        )
        await store.save()

        resp.media = {"code": 0, "message": "创建成功", "data": store.dict()}


class StoreDetailResource:
    async def on_get(self, req, resp, store_id):
        try:
            store = await Store.objects.get(id=store_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="门店不存在")

        data = store.dict()
        try:
            rooms = await store.fitting_rooms.all()
            data["fitting_rooms"] = [r.dict() for r in rooms]
        except Exception:
            data["fitting_rooms"] = []

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_put(self, req, resp, store_id):
        try:
            store = await Store.objects.get(id=store_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="门店不存在")

        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        if "name" in data and data["name"]:
            store.name = data["name"]
        if "floor" in data and data["floor"]:
            store.floor = int(data["floor"])
        if "location" in data:
            store.location = data.get("location", "")
        if "phone" in data:
            store.phone = data.get("phone")
        if "manager" in data:
            store.manager = data.get("manager")
        if "status" in data:
            store.status = bool(data.get("status"))

        await store.update()
        resp.media = {"code": 0, "message": "更新成功", "data": store.dict()}

    async def on_delete(self, req, resp, store_id):
        try:
            store = await Store.objects.get(id=store_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="门店不存在")

        try:
            rooms = await store.fitting_rooms.all()
            if rooms:
                raise falcon.HTTPBadRequest(title="删除失败", description="该门店下还有试衣间，无法删除")
        except falcon.HTTPBadRequest:
            raise
        except Exception:
            pass

        await store.delete()
        resp.media = {"code": 0, "message": "删除成功"}


class FloorListResource:
    async def on_get(self, req, resp):
        stores = await Store.objects.all()
        floors = list(set(s.floor for s in stores))
        floors.sort()
        resp.media = {"code": 0, "message": "获取成功", "data": floors}
