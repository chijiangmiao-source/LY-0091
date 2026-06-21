from datetime import datetime

from app.services.base import BaseService
from app.services.member_service import member_service
from app.exceptions import (
    NotFoundError, StateConflictError, ValidationError
)
from app.models import (
    LostItem, FittingRoom, QueueRecord, User, LOST_ITEM_STATUS
)


class LostItemService(BaseService):

    async def register_lost_item(
        self,
        item_name: str,
        fitting_room_id: int,
        item_description: str = "",
        item_category: str = None,
        queue_record_id: int = None,
        register_user: User = None
    ) -> LostItem:
        if not item_name:
            raise ValidationError("物品名称不能为空")
        if not fitting_room_id:
            raise ValidationError("请选择试衣间")

        try:
            room = await FittingRoom.objects.get(id=fitting_room_id)
        except Exception:
            raise ValidationError("试衣间不存在")

        queue_record = None
        if queue_record_id:
            try:
                queue_record = await QueueRecord.objects.get(id=queue_record_id)
            except Exception:
                pass

        item = LostItem(
            item_name=item_name,
            item_description=item_description,
            item_category=item_category,
            fitting_room=room,
            queue_record=queue_record,
            register_user=register_user,
            status="registered"
        )
        await item.save()

        if queue_record:
            await member_service.record_behavior(
                phone=queue_record.phone,
                behavior_type="lost_item",
                related_id=item.id,
                detail=f"遗留物登记：{item_name}"
            )

        self.log.info("register_lost_item", f"item={item_name}, room={room.room_number}")
        return item

    async def get_lost_item_detail(self, item_id: int) -> dict:
        try:
            item = await LostItem.objects.select_related(
                "fitting_room", "queue_record",
                "register_user", "seal_user", "claim_user"
            ).get(id=item_id)
        except Exception:
            raise NotFoundError("遗留物记录不存在")

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
        return data

    async def seal_lost_item(
        self,
        item_id: int,
        seal_location: str,
        seal_user: User = None
    ) -> None:
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise NotFoundError("遗留物记录不存在")

        if item.status not in ["registered"]:
            raise StateConflictError("当前状态不支持封存", title="操作失败")

        if not seal_location:
            raise ValidationError("请填写封存位置")

        item.seal_location = seal_location
        item.seal_time = datetime.now()
        item.seal_user = seal_user
        item.status = "sealed"
        await item.update()

        self.log.info("seal_lost_item", f"item_id={item_id}")

    async def claim_lost_item(
        self,
        item_id: int,
        claimant_name: str,
        claimant_phone: str,
        claimant_id_number: str,
        verify_code: str = None,
        claim_user: User = None
    ) -> None:
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise NotFoundError("遗留物记录不存在")

        if item.status == "claimed":
            raise StateConflictError("该物品已被认领，不能重复认领", title="操作失败")

        if item.status != "sealed":
            raise StateConflictError("物品未正式封存，不能认领", title="操作失败")

        if not claimant_name:
            raise ValidationError("请填写认领人姓名")
        if not claimant_phone:
            raise ValidationError("请填写认领人手机号")
        if not claimant_id_number:
            raise ValidationError("请填写认领人证件号")

        await member_service.validate_blacklist_for_scene(
            phone=claimant_phone,
            scene="claim",
            verify_code=verify_code,
            scene_label="办理认领"
        )

        item.claimant_name = claimant_name
        item.claimant_phone = claimant_phone
        item.claimant_id_number = claimant_id_number
        item.claim_time = datetime.now()
        item.claim_user = claim_user
        item.claim_verified = True
        item.status = "claimed"
        await item.update()

        if item.fitting_room:
            if item.fitting_room.status == "sealed":
                item.fitting_room.status = "cleaning"
                await item.fitting_room.update()

        await member_service.record_behavior(
            phone=claimant_phone,
            behavior_type="claim",
            related_id=item.id,
            detail=f"认领物品：{item.item_name}，认领人：{claimant_name}"
        )

        self.log.info("claim_lost_item", f"item_id={item_id}, claimant={claimant_phone}")

    async def dispose_lost_item(
        self,
        item_id: int,
        remark: str = None
    ) -> None:
        try:
            item = await LostItem.objects.select_related("fitting_room").get(id=item_id)
        except Exception:
            raise NotFoundError("遗留物记录不存在")

        if item.status not in ["sealed", "registered"]:
            raise StateConflictError("当前状态不支持处理", title="操作失败")

        item.status = "disposed"
        item.remark = (remark or item.remark or "") + " | 已按无主物品处理"
        await item.update()

        if item.fitting_room:
            if item.fitting_room.status == "sealed":
                item.fitting_room.status = "cleaning"
                await item.fitting_room.update()

        self.log.info("dispose_lost_item", f"item_id={item_id}")

    async def list_lost_items(
        self,
        status: str = None,
        room_id: int = None
    ) -> list:
        query = LostItem.objects.select_related(
            "fitting_room", "queue_record",
            "register_user", "seal_user", "claim_user"
        )

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

        return result


lost_item_service = LostItemService()
