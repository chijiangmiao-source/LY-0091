import falcon
import json
from datetime import datetime
from app.models import LostItem, FittingRoom, QueueRecord, User, LOST_ITEM_STATUS
from app.routes.member import check_blacklist, record_behavior


class LostItemListResource:
    async def on_get(self, req, resp):
        status = req.get_param("status")
        room_id = req.get_param_as_int("room_id")

        query = LostItem.objects.select_related("fitting_room", "queue_record",
                                                 "register_user", "seal_user", "claim_user")

        if status:
            statuses = status.split(",")
            query = query.filter(status__in=statuses)
        if room_id is not None:
            query = query.filter(fitting_room__id=room_id)

        items = await query.order_by("-register_time").all()
        result = []
        for item in items:
            data = item.dict()
            if item.fitting_room:
                data["room_number"] = item.fitting_room.room_number
            if item.queue_record:
                data["ticket_number"] = item.queue_record.ticket_number
                data["customer_phone"] = item.queue_record.phone
            if item.register_user:
                data["register_user_name"] = item.register_user.real_name
            if item.seal_user:
                data["seal_user_name"] = item.seal_user.real_name
            if item.claim_user:
                data["claim_user_name"] = item.claim_user.real_name
            data["status_text"] = LOST_ITEM_STATUS.get(item.status, item.status)
            result.append(data)

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        current_user = req.context.get("user")

        if not data.get("item_name"):
            raise falcon.HTTPBadRequest(title="参数错误", description="物品名称不能为空")
        if not data.get("fitting_room_id"):
            raise falcon.HTTPBadRequest(title="参数错误", description="请选择试衣间")

        try:
            room = await FittingRoom.objects.get(id=data.get("fitting_room_id"))
        except Exception:
            raise falcon.HTTPBadRequest(title="参数错误", description="试衣间不存在")

        queue_record = None
        if data.get("queue_record_id"):
            try:
                queue_record = await QueueRecord.objects.get(id=data.get("queue_record_id"))
            except Exception:
                pass

        item = LostItem(
            item_name=data.get("item_name"),
            item_description=data.get("item_description", ""),
            item_category=data.get("item_category"),
            fitting_room=room,
            queue_record=queue_record,
            register_user=current_user,
            status="registered"
        )
        await item.save()

        resp.media = {"code": 0, "message": "登记成功", "data": item.dict()}


class LostItemDetailResource:
    async def on_get(self, req, resp, item_id):
        try:
            item = await LostItem.objects.select_related(
                "fitting_room", "queue_record",
                "register_user", "seal_user", "claim_user"
            ).get(id=item_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="遗留物记录不存在")

        data = item.dict()
        if item.fitting_room:
            data["room_number"] = item.fitting_room.room_number
        if item.queue_record:
            data["ticket_number"] = item.queue_record.ticket_number
        if item.register_user:
            data["register_user_name"] = item.register_user.real_name
        if item.seal_user:
            data["seal_user_name"] = item.seal_user.real_name
        if item.claim_user:
            data["claim_user_name"] = item.claim_user.real_name
        data["status_text"] = LOST_ITEM_STATUS.get(item.status, item.status)

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class LostItemSealResource:
    async def on_post(self, req, resp, item_id):
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="遗留物记录不存在")

        if item.status not in ["registered"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="当前状态不支持封存")

        try:
            data = await req.get_media()
        except Exception:
            data = {}

        if not data.get("seal_location"):
            raise falcon.HTTPBadRequest(title="参数错误", description="请填写封存位置")

        current_user = req.context.get("user")

        item.seal_location = data.get("seal_location")
        item.seal_time = datetime.now()
        item.seal_user = current_user
        item.status = "sealed"
        await item.update()

        resp.media = {"code": 0, "message": "封存成功，物品已妥善保管"}


class LostItemClaimResource:
    async def on_post(self, req, resp, item_id):
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="遗留物记录不存在")

        if item.status == "claimed":
            raise falcon.HTTPBadRequest(title="操作失败", description="该物品已被认领，不能重复认领")

        if item.status != "sealed":
            raise falcon.HTTPBadRequest(title="操作失败", description="物品未正式封存，不能认领")

        try:
            data = await req.get_media()
        except Exception:
            data = {}

        if not data.get("claimant_name"):
            raise falcon.HTTPBadRequest(title="参数错误", description="请填写认领人姓名")
        if not data.get("claimant_phone"):
            raise falcon.HTTPBadRequest(title="参数错误", description="请填写认领人手机号")
        if not data.get("claimant_id_number"):
            raise falcon.HTTPBadRequest(title="参数错误", description="请填写认领人证件号")

        claimant_phone = (data.get("claimant_phone") or "").strip()
        blacklist_result = await check_blacklist(claimant_phone, "claim")
        if blacklist_result["is_blocked"]:
            raise falcon.HTTPBadRequest(
                title="认领失败",
                description=f"认领人手机号已被加入黑名单，无法办理认领。原因：{blacklist_result['reason']}"
            )
        if blacklist_result["is_gray"]:
            need_verify = data.get("verify_code")
            if not need_verify:
                raise falcon.HTTPBadRequest(
                    title="需要二次校验",
                    description=f"认领人手机号处于灰名单，需工作人员确认后方可认领。原因：{blacklist_result['reason']}"
                )

        current_user = req.context.get("user")

        item.claimant_name = data.get("claimant_name")
        item.claimant_phone = data.get("claimant_phone")
        item.claimant_id_number = data.get("claimant_id_number")
        item.claim_time = datetime.now()
        item.claim_user = current_user
        item.claim_verified = True
        item.status = "claimed"
        await item.update()

        if item.fitting_room:
            if item.fitting_room.status == "sealed":
                item.fitting_room.status = "cleaning"
                await item.fitting_room.update()

        await record_behavior(
            phone=claimant_phone,
            behavior_type="claim",
            related_id=item.id,
            detail=f"认领物品：{item.item_name}，认领人：{data.get('claimant_name')}"
        )

        resp.media = {"code": 0, "message": "认领登记成功"}


class LostItemDisposeResource:
    async def on_post(self, req, resp, item_id):
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="遗留物记录不存在")

        if item.status not in ["sealed", "registered"]:
            raise falcon.HTTPBadRequest(title="操作失败", description="当前状态不支持处理")

        try:
            data = await req.get_media()
        except Exception:
            data = {}

        item.status = "disposed"
        item.remark = data.get("remark", item.remark) + " | 已按无主物品处理"
        await item.update()

        if item.fitting_room:
            if item.fitting_room.status == "sealed":
                item.fitting_room.status = "cleaning"
                await item.fitting_room.update()

        resp.media = {"code": 0, "message": "已标记为处理完成"}


class LostItemStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in LOST_ITEM_STATUS.items()]
        }
