from datetime import datetime, timedelta
from collections import defaultdict

from app.services.base import BaseService
from app.services.member_service import member_service
from app.services.queue_service import queue_service
from app.exceptions import NotFoundError, StateConflictError, ValidationError
from app.models import (
    StoreTransfer, TransferLostItemLink,
    TRANSFER_STATUS, TRANSFER_REASON, TRANSFER_SOURCE_TYPE,
    CUSTOMER_CONFIRM_STATUS, TRANSFER_ITEM_TRACKING_STATUS,
    LOAD_LEVEL_TEXT, calc_floor_distance, classify_load_level,
    generate_transfer_no,
    Store, FittingRoom, ROOM_TYPES, ROOM_STATUS,
    QueueRecord, QUEUE_STATUS, QUEUE_SOURCE,
    Appointment, APPOINTMENT_STATUS,
    LostItem, LOST_ITEM_STATUS,
    MemberProfile,
)


WEIGHT_DISTANCE = 0.35
WEIGHT_LOAD = 0.30
WEIGHT_ROOM_MATCH = 0.20
WEIGHT_MEMBER_LEVEL = 0.15

MAX_RECOMMEND_COUNT = 5
MAX_FLOOR_DISTANCE = 5

MEMBER_LEVEL_SCORES = {
    "vip": 100,
    "high_frequency": 75,
    "normal": 50,
    "gray": 30,
    "risk": 20,
}


class TransferService(BaseService):

    async def get_store_load_info(self, store_id: int) -> dict:
        store = await Store.objects.filter(id=store_id, status=True).first()
        if not store:
            return None

        try:
            all_rooms = await store.fitting_rooms.all()
        except Exception:
            all_rooms = []

        active_rooms = [r for r in all_rooms if r.status != "sealed"]
        room_count = len(active_rooms)

        available_rooms = [r for r in active_rooms if r.status == "available"]
        available_count = len(available_rooms)

        waiting_count = await QueueRecord.objects.filter(
            store__id=store_id,
            status__in=["waiting", "called"]
        ).count()

        room_type_counts = defaultdict(int)
        room_type_available = defaultdict(int)
        for r in active_rooms:
            room_type_counts[r.room_type] += 1
            if r.status == "available":
                room_type_available[r.room_type] += 1

        room_type_waiting = defaultdict(int)
        waiting_records = await QueueRecord.objects.filter(
            store__id=store_id,
            status="waiting"
        ).all()
        for wr in waiting_records:
            if wr.fitting_room:
                room_type_waiting[wr.fitting_room.room_type] += 1
            else:
                room_type_waiting["standard"] += 1

        load_level = classify_load_level(waiting_count, room_count)

        return {
            "store_id": store.id,
            "store_name": store.name,
            "floor": store.floor,
            "room_count": room_count,
            "available_count": available_count,
            "waiting_count": waiting_count,
            "load_level": load_level,
            "load_level_text": LOAD_LEVEL_TEXT.get(load_level, load_level),
            "room_type_counts": dict(room_type_counts),
            "room_type_available": dict(room_type_available),
            "room_type_waiting": dict(room_type_waiting),
        }

    def get_member_level_score(self, member: MemberProfile, phone: str) -> int:
        if not member:
            return MEMBER_LEVEL_SCORES["normal"]

        tags = member.get_tags_list()
        if "vip" in tags:
            return MEMBER_LEVEL_SCORES["vip"]
        if "high_frequency" in tags:
            return MEMBER_LEVEL_SCORES["high_frequency"]
        if member.blacklist_status == "gray":
            return MEMBER_LEVEL_SCORES["gray"]

        risk_tags = {"easy_no_show", "lost_item_risk", "frequent_overtime"}
        if any(t in tags for t in risk_tags):
            return MEMBER_LEVEL_SCORES["risk"]

        return MEMBER_LEVEL_SCORES["normal"]

    async def recommend_target_stores(
        self,
        source_store_id: int,
        room_type: str = "standard",
        phone: str = None,
        limit: int = MAX_RECOMMEND_COUNT
    ) -> list:
        source_store = await Store.objects.filter(id=source_store_id).first()
        if not source_store:
            return []

        all_stores = await Store.objects.filter(status=True, id__ne=source_store_id).all()
        if not all_stores:
            return []

        member = None
        if phone:
            member = await MemberProfile.objects.filter(phone=phone).first()
        member_score = self.get_member_level_score(member, phone)

        source_load = await self.get_store_load_info(source_store_id)
        source_floor = source_store.floor

        candidates = []

        for store in all_stores:
            floor_dist = calc_floor_distance(source_floor, store.floor)
            if floor_dist > MAX_FLOOR_DISTANCE:
                continue

            load_info = await self.get_store_load_info(store.id)
            if not load_info:
                continue

            dist_score = max(0, 100 - (floor_dist * (100 / MAX_FLOOR_DISTANCE)))

            waiting_count = load_info["waiting_count"]
            room_count = max(1, load_info["room_count"])
            load_ratio = min(waiting_count / room_count, 4.0)
            load_score = max(0, 100 - (load_ratio * 25))

            rt_total = load_info["room_type_counts"].get(room_type, 0)
            rt_avail = load_info["room_type_available"].get(room_type, 0)
            rt_waiting = load_info["room_type_waiting"].get(room_type, 0)

            if rt_total > 0:
                avail_ratio = rt_avail / rt_total
                wait_pressure = max(0, 1 - (rt_waiting / max(1, rt_total)))
                room_match_score = (avail_ratio * 60) + (wait_pressure * 40)
                if rt_avail > 0:
                    room_match_score = min(100, room_match_score + 20)
            else:
                fallback_rt_avail = load_info["available_count"]
                fallback_rt_total = load_info["room_count"]
                if fallback_rt_total > 0:
                    room_match_score = (fallback_rt_avail / fallback_rt_total) * 50
                else:
                    room_match_score = 0

            total_score = (
                dist_score * WEIGHT_DISTANCE
                + load_score * WEIGHT_LOAD
                + room_match_score * WEIGHT_ROOM_MATCH
                + member_score * WEIGHT_MEMBER_LEVEL
            )

            if load_info["load_level"] == "critical":
                total_score *= 0.6
            elif load_info["load_level"] == "high":
                total_score *= 0.85

            candidates.append({
                "store_id": store.id,
                "store_name": store.name,
                "floor": store.floor,
                "location": store.location,
                "phone": store.phone,
                "manager": store.manager,
                "floor_distance": floor_dist,
                "floor_distance_text": f"{'楼上' if store.floor > source_floor else '楼下'} {floor_dist} 层" if floor_dist > 0 else "同层",
                "dist_score": round(dist_score, 1),
                "load_score": round(load_score, 1),
                "room_match_score": round(room_match_score, 1),
                "member_score": round(member_score, 1),
                "total_score": round(total_score, 1),
                "room_count": load_info["room_count"],
                "available_count": load_info["available_count"],
                "waiting_count": load_info["waiting_count"],
                "load_level": load_info["load_level"],
                "load_level_text": load_info["load_level_text"],
                "room_type_available": load_info["room_type_available"].get(room_type, 0),
                "room_type_total": load_info["room_type_counts"].get(room_type, 0),
                "room_type_waiting": load_info["room_type_waiting"].get(room_type, 0),
            })

        candidates.sort(key=lambda x: x["total_score"], reverse=True)
        return candidates[:limit]

    async def handle_lost_items_transfer(
        self,
        source_queue_id: int,
        transfer: StoreTransfer,
        user=None
    ) -> list:
        queue = await QueueRecord.objects.filter(id=source_queue_id).first()
        if not queue or not queue.fitting_room:
            return []

        lost_items = await LostItem.objects.filter(
            queue_record__id=queue.id,
            status__in=["registered", "sealed"]
        ).all()

        links = []
        for li in lost_items:
            link = TransferLostItemLink(
                transfer=transfer,
                lost_item_id=li.id,
                original_store=transfer.source_store,
                current_store=transfer.target_store,
                tracking_status="transiting",
                handover_by=user,
                handover_time=datetime.now(),
            )
            await link.save()
            links.append(link)

        return links

    async def _execute_queue_transfer(self, transfer: StoreTransfer, user=None):
        source_queue = await QueueRecord.objects.select_related(
            "store", "fitting_room"
        ).filter(id=transfer.source_queue_id).first()

        if source_queue:
            if source_queue.status in ["waiting", "called"]:
                source_queue.status = "abnormal"
                source_queue.is_abnormal = True
                source_queue.abnormal_reason = f"已跨店转单至【{transfer.target_store.name if transfer.target_store else '目标门店'}】，转单号：{transfer.transfer_no}"
                await source_queue.update()

        ticket_number = await queue_service.generate_ticket_number(
            transfer.target_store.id if transfer.target_store else None
        )
        new_queue = QueueRecord(
            ticket_number=ticket_number,
            store=transfer.target_store,
            customer_name=transfer.customer_name,
            phone=transfer.phone,
            status="waiting",
            source=source_queue.source if source_queue else "on_site",
            appointment_id=source_queue.appointment_id if source_queue else None,
            remark=f"跨店转单来源：{transfer.source_store.name if transfer.source_store else '公共'}，"
                   f"原号码：{transfer.original_ticket_no}，转单号：{transfer.transfer_no}"
                   f"{'（VIP优先）' if transfer.priority_boost else ''}",
            queue_time=datetime.now(),
        )
        await new_queue.save()

        if transfer.priority_boost:
            waiting_same_type = await QueueRecord.objects.filter(
                store__id=transfer.target_store.id if transfer.target_store else None,
                status="waiting"
            ).count()
            if waiting_same_type > 1:
                new_queue.remark += f"，优先级别：前{min(3, waiting_same_type)}位叫号"
                await new_queue.update()

        transfer.new_queue_id = new_queue.id
        return new_queue

    async def _execute_appointment_transfer(self, transfer: StoreTransfer, user=None):
        source_apt = await Appointment.objects.select_related(
            "store"
        ).filter(id=transfer.source_appointment_id).first()

        if source_apt and source_apt.status == "pending":
            source_apt.status = "cancelled"
            source_apt.cancelled_at = datetime.now()
            source_apt.cancel_reason = f"已跨店转单至【{transfer.target_store.name if transfer.target_store else '目标门店'}】，转单号：{transfer.transfer_no}"
            await source_apt.update()

        if source_apt:
            new_apt_no = f"{source_apt.appointment_no}-T{transfer.id}"
        else:
            from app.services.appointment_service import appointment_service
            new_apt_no = await appointment_service.generate_appointment_no()

        new_apt = Appointment(
            appointment_no=new_apt_no,
            store=transfer.target_store,
            customer_name=transfer.customer_name,
            phone=transfer.phone,
            room_type=transfer.room_type,
            appointment_date=source_apt.appointment_date if source_apt else datetime.now().strftime("%Y-%m-%d"),
            time_slot=source_apt.time_slot if source_apt else "09:00-09:30",
            status="pending",
            remark=f"跨店转单来源：{transfer.source_store.name if transfer.source_store else '公共'}，"
                   f"原预约号：{transfer.original_ticket_no}，转单号：{transfer.transfer_no}，"
                   f"预约时段继承：{'是' if source_apt else '否'}"
                   f"{'（VIP优先）' if transfer.priority_boost else ''}",
        )
        await new_apt.save()

        transfer.new_appointment_id = new_apt.id
        return new_apt

    async def execute_transfer(self, transfer: StoreTransfer, user=None) -> StoreTransfer:
        if transfer.source_type == "queue":
            await self._execute_queue_transfer(transfer, user)
        elif transfer.source_type == "appointment":
            await self._execute_appointment_transfer(transfer, user)

        if transfer.source_queue_id:
            await self.handle_lost_items_transfer(transfer.source_queue_id, transfer, user)

        transfer.status = "completed"
        transfer.completed_at = datetime.now()
        transfer.updated_at = datetime.now()
        await transfer.update()

        await member_service.record_behavior(
            phone=transfer.phone,
            behavior_type="transfer_in",
            related_id=transfer.id,
            store_name=transfer.target_store.name if transfer.target_store else None,
            detail=f"转单到达：{transfer.transfer_no}，已转入【{transfer.target_store.name if transfer.target_store else '目标门店'}】"
        )
        await member_service.record_behavior(
            phone=transfer.phone,
            behavior_type="transfer_completed",
            related_id=transfer.id,
            store_name=transfer.target_store.name if transfer.target_store else None,
            detail=f"转单完成：{transfer.transfer_no}"
        )

        await member_service.refresh_member_stats(transfer.phone)
        self.log.info("execute_transfer", f"transfer_no={transfer.transfer_no}")
        return transfer

    async def create_transfer_for_queue(
        self,
        queue_id: int,
        target_store_id: int,
        reason: str,
        reason_detail: str = None,
        user=None
    ) -> StoreTransfer:
        queue = await QueueRecord.objects.select_related("store", "fitting_room").get(id=queue_id)

        source_store = queue.store
        if source_store and source_store.id == target_store_id:
            raise StateConflictError("目标门店不能与源门店相同", title="转单失败")

        target_store = await Store.objects.get(id=target_store_id)

        room_type = queue.fitting_room.room_type if queue.fitting_room else "standard"

        transfer_no = await generate_transfer_no()

        transfer = StoreTransfer(
            transfer_no=transfer_no,
            source_type="queue",
            source_queue_id=queue.id,
            original_source=queue.source,
            original_ticket_no=queue.ticket_number,
            source_store=source_store,
            target_store=target_store,
            customer_name=queue.customer_name,
            phone=queue.phone,
            room_type=room_type,
            transfer_reason=reason,
            transfer_reason_detail=reason_detail,
            status="pending",
            customer_confirm_status="pending",
        )

        if user:
            transfer.operator = user
            transfer.operator_name = user.real_name

        if source_store:
            source_load = await self.get_store_load_info(source_store.id)
            if source_load:
                transfer.source_load_level = source_load["load_level"]

        target_load = await self.get_store_load_info(target_store.id)
        if target_load:
            transfer.target_load_level = target_load["load_level"]

        if source_store and target_store:
            transfer.floor_distance = calc_floor_distance(source_store.floor, target_store.floor)

        member = await MemberProfile.objects.filter(phone=queue.phone).first()
        if member:
            tags = member.get_tags_list()
            if "vip" in tags or "high_frequency" in tags:
                transfer.priority_boost = True
                transfer.priority_note = "VIP/高频顾客转单，目标门店优先叫号"

        await transfer.save()

        await member_service.record_behavior(
            phone=queue.phone,
            behavior_type="transfer_out",
            related_id=transfer.id,
            store_name=source_store.name if source_store else None,
            detail=f"发起转单：{transfer_no}，原因：{TRANSFER_REASON.get(reason, reason)}，"
                   f"从【{source_store.name if source_store else '公共'}】转至【{target_store.name}】",
            user_id=user.id if user else None
        )

        self.log.info("create_transfer_queue", f"transfer_no={transfer_no}")
        return transfer

    async def create_transfer_for_appointment(
        self,
        appointment_id: int,
        target_store_id: int,
        reason: str,
        reason_detail: str = None,
        user=None
    ) -> StoreTransfer:
        apt = await Appointment.objects.select_related("store").get(id=appointment_id)

        source_store = apt.store
        if source_store and source_store.id == target_store_id:
            raise StateConflictError("目标门店不能与源门店相同", title="转单失败")

        target_store = await Store.objects.get(id=target_store_id)

        transfer_no = await generate_transfer_no()

        transfer = StoreTransfer(
            transfer_no=transfer_no,
            source_type="appointment",
            source_appointment_id=apt.id,
            original_source="appointment",
            original_ticket_no=apt.appointment_no,
            source_store=source_store,
            target_store=target_store,
            customer_name=apt.customer_name,
            phone=apt.phone,
            room_type=apt.room_type,
            transfer_reason=reason,
            transfer_reason_detail=reason_detail,
            status="pending",
            customer_confirm_status="pending",
        )

        if user:
            transfer.operator = user
            transfer.operator_name = user.real_name

        if source_store:
            source_load = await self.get_store_load_info(source_store.id)
            if source_load:
                transfer.source_load_level = source_load["load_level"]

        target_load = await self.get_store_load_info(target_store.id)
        if target_load:
            transfer.target_load_level = target_load["load_level"]

        if source_store and target_store:
            transfer.floor_distance = calc_floor_distance(source_store.floor, target_store.floor)

        member = await MemberProfile.objects.filter(phone=apt.phone).first()
        if member:
            tags = member.get_tags_list()
            if "vip" in tags or "high_frequency" in tags:
                transfer.priority_boost = True
                transfer.priority_note = "VIP/高频顾客转单，目标门店优先安排时段"

        await transfer.save()

        await member_service.record_behavior(
            phone=apt.phone,
            behavior_type="transfer_out",
            related_id=transfer.id,
            store_name=source_store.name if source_store else None,
            detail=f"发起预约转单：{transfer_no}，原因：{TRANSFER_REASON.get(reason, reason)}，"
                   f"从【{source_store.name if source_store else '公共'}】转至【{target_store.name}】",
            user_id=user.id if user else None
        )

        self.log.info("create_transfer_appointment", f"transfer_no={transfer_no}")
        return transfer

    async def customer_confirm_transfer(
        self,
        transfer_id: int,
        confirmed: bool,
        note: str = None
    ) -> StoreTransfer:
        transfer = await StoreTransfer.objects.select_related(
            "source_store", "target_store"
        ).get(id=transfer_id)

        if transfer.customer_confirm_status != "pending":
            raise StateConflictError(
                f"当前确认状态：{CUSTOMER_CONFIRM_STATUS.get(transfer.customer_confirm_status)}，不可重复操作",
                title="操作失败"
            )

        transfer.customer_confirm_time = datetime.now()
        transfer.customer_confirm_note = note
        transfer.updated_at = datetime.now()

        if confirmed:
            transfer.customer_confirm_status = "confirmed"
            transfer.status = "customer_confirmed"
            await transfer.update()

            await member_service.record_behavior(
                phone=transfer.phone,
                behavior_type="transfer_customer_confirm",
                related_id=transfer.id,
                store_name=transfer.target_store.name if transfer.target_store else None,
                detail=f"顾客确认转单：{transfer.transfer_no}，前往【{transfer.target_store.name if transfer.target_store else '目标门店'}】"
            )
        else:
            transfer.customer_confirm_status = "rejected"
            transfer.status = "customer_rejected"
            transfer.cancelled_at = datetime.now()
            await transfer.update()

            await member_service.record_behavior(
                phone=transfer.phone,
                behavior_type="transfer_customer_reject",
                related_id=transfer.id,
                store_name=transfer.source_store.name if transfer.source_store else None,
                detail=f"顾客拒绝转单：{transfer.transfer_no}，原因：{note or '未说明'}"
            )

        self.log.info("customer_confirm", f"transfer_no={transfer.transfer_no}, confirmed={confirmed}")
        return transfer

    async def target_store_accept_transfer(
        self,
        transfer_id: int,
        accepted: bool,
        reject_reason: str = None,
        user=None
    ) -> StoreTransfer:
        transfer = await StoreTransfer.objects.select_related(
            "source_store", "target_store"
        ).get(id=transfer_id)

        if transfer.status not in ["customer_confirmed"]:
            raise StateConflictError(
                f"当前状态：{TRANSFER_STATUS.get(transfer.status)}，需顾客确认后才能操作",
                title="操作失败"
            )

        transfer.updated_at = datetime.now()

        if accepted:
            transfer.target_store_accepted = True
            transfer.target_store_accept_time = datetime.now()
            transfer.status = "target_accepted"
            await transfer.update()

            await self.execute_transfer(transfer, user)
        else:
            transfer.target_store_accepted = False
            transfer.target_store_reject_reason = reject_reason or "目标门店无法承接"
            transfer.status = "target_rejected"
            transfer.cancelled_at = datetime.now()
            await transfer.update()

            await member_service.record_behavior(
                phone=transfer.phone,
                behavior_type="transfer_failed",
                related_id=transfer.id,
                store_name=transfer.target_store.name if transfer.target_store else None,
                detail=f"目标门店拒绝转单：{transfer.transfer_no}，原因：{reject_reason or '未说明'}"
            )

        self.log.info("target_accept", f"transfer_no={transfer.transfer_no}, accepted={accepted}")
        return transfer

    async def cancel_transfer(
        self,
        transfer_id: int,
        cancel_reason: str = "操作员取消",
        user=None
    ) -> StoreTransfer:
        try:
            transfer = await StoreTransfer.objects.select_related(
                "source_store", "target_store"
            ).get(id=transfer_id)
        except Exception:
            raise NotFoundError("转单记录不存在")

        if transfer.status in ["completed", "cancelled", "customer_rejected", "target_rejected", "failed"]:
            raise StateConflictError(
                f"当前状态：{TRANSFER_STATUS.get(transfer.status)}，不可取消",
                title="操作失败"
            )

        transfer.status = "cancelled"
        transfer.cancelled_at = datetime.now()
        transfer.updated_at = datetime.now()
        transfer.remark = f"取消原因：{cancel_reason}"
        await transfer.update()

        await member_service.record_behavior(
            phone=transfer.phone,
            behavior_type="transfer_failed",
            related_id=transfer.id,
            store_name=transfer.source_store.name if transfer.source_store else None,
            detail=f"转单取消：{transfer.transfer_no}，原因：{cancel_reason}",
            user_id=user.id if user else None
        )

        self.log.info("cancel_transfer", f"transfer_no={transfer.transfer_no}")
        return transfer

    async def get_transfer_detail(self, transfer_id: int) -> dict:
        try:
            transfer = await StoreTransfer.objects.select_related(
                "source_store", "target_store", "operator"
            ).get(id=transfer_id)
        except Exception:
            raise NotFoundError("转单记录不存在")

        data = transfer.dict()
        if transfer.source_store:
            data["source_store_name"] = transfer.source_store.name
        if transfer.target_store:
            data["target_store_name"] = transfer.target_store.name
        if transfer.operator:
            data["operator_real_name"] = transfer.operator.real_name
        data["status_text"] = transfer.get_status_text()
        data["reason_text"] = transfer.get_reason_text()
        data["source_type_text"] = transfer.get_source_type_text()
        data["room_type_text"] = transfer.get_room_type_text()
        data["customer_confirm_text"] = transfer.get_customer_confirm_text()

        if transfer.source_queue_id:
            try:
                src_queue = await QueueRecord.objects.select_related("fitting_room").get(id=transfer.source_queue_id)
                data["source_queue"] = {
                    "id": src_queue.id,
                    "ticket_number": src_queue.ticket_number,
                    "status": src_queue.status,
                    "status_text": QUEUE_STATUS.get(src_queue.status, src_queue.status),
                    "room_number": src_queue.fitting_room.room_number if src_queue.fitting_room else None,
                }
            except Exception:
                data["source_queue"] = None

        if transfer.source_appointment_id:
            try:
                src_apt = await Appointment.objects.get(id=transfer.source_appointment_id)
                data["source_appointment"] = {
                    "id": src_apt.id,
                    "appointment_no": src_apt.appointment_no,
                    "status": src_apt.status,
                    "status_text": APPOINTMENT_STATUS.get(src_apt.status, src_apt.status),
                    "appointment_date": src_apt.appointment_date,
                    "time_slot": src_apt.time_slot,
                }
            except Exception:
                data["source_appointment"] = None

        if transfer.new_queue_id:
            try:
                new_queue = await QueueRecord.objects.select_related("fitting_room", "store").get(id=transfer.new_queue_id)
                data["new_queue"] = {
                    "id": new_queue.id,
                    "ticket_number": new_queue.ticket_number,
                    "status": new_queue.status,
                    "status_text": QUEUE_STATUS.get(new_queue.status, new_queue.status),
                    "store_name": new_queue.store.name if new_queue.store else None,
                    "room_number": new_queue.fitting_room.room_number if new_queue.fitting_room else None,
                }
            except Exception:
                data["new_queue"] = None

        if transfer.new_appointment_id:
            try:
                new_apt = await Appointment.objects.select_related("store").get(id=transfer.new_appointment_id)
                data["new_appointment"] = {
                    "id": new_apt.id,
                    "appointment_no": new_apt.appointment_no,
                    "status": new_apt.status,
                    "status_text": APPOINTMENT_STATUS.get(new_apt.status, new_apt.status),
                    "store_name": new_apt.store.name if new_apt.store else None,
                    "appointment_date": new_apt.appointment_date,
                    "time_slot": new_apt.time_slot,
                }
            except Exception:
                data["new_appointment"] = None

        lost_links = await TransferLostItemLink.objects.select_related(
            "original_store", "current_store"
        ).filter(transfer__id=transfer_id).all()
        lost_items_info = []
        for link in lost_links:
            try:
                li = await LostItem.objects.get(id=link.lost_item_id)
                lost_items_info.append({
                    "link_id": link.id,
                    "lost_item_id": li.id,
                    "item_name": li.item_name,
                    "item_description": li.item_description,
                    "status": li.status,
                    "status_text": LOST_ITEM_STATUS.get(li.status, li.status),
                    "original_store_name": link.original_store.name if link.original_store else None,
                    "current_store_name": link.current_store.name if link.current_store else None,
                    "tracking_status": link.tracking_status,
                    "tracking_status_text": TRANSFER_ITEM_TRACKING_STATUS.get(link.tracking_status, link.tracking_status),
                })
            except Exception:
                pass
        data["lost_items"] = lost_items_info

        return data

    async def list_transfers(
        self,
        source_store_id: int = None,
        target_store_id: int = None,
        store_id: int = None,
        status: str = None,
        phone: str = None,
        source_type: str = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        query = StoreTransfer.objects.select_related(
            "source_store", "target_store", "operator"
        )

        if source_store_id is not None:
            query = query.filter(source_store__id=source_store_id)
        if target_store_id is not None:
            query = query.filter(target_store__id=target_store_id)
        if store_id is not None:
            query = query.filter(
                (StoreTransfer.source_store.id == store_id) |
                (StoreTransfer.target_store.id == store_id)
            )
        if status:
            statuses = status.split(",")
            query = query.filter(status__in=statuses)
        if phone:
            query = query.filter(phone=phone)
        if source_type:
            query = query.filter(source_type=source_type)

        total = await query.count()
        records = await query.order_by("-created_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for t in records:
            data = t.dict()
            if t.source_store:
                data["source_store_name"] = t.source_store.name
            if t.target_store:
                data["target_store_name"] = t.target_store.name
            if t.operator:
                data["operator_real_name"] = t.operator.real_name
            data["status_text"] = t.get_status_text()
            data["reason_text"] = t.get_reason_text()
            data["source_type_text"] = t.get_source_type_text()
            data["room_type_text"] = t.get_room_type_text()
            data["customer_confirm_text"] = t.get_customer_confirm_text()
            result.append(data)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": result
        }

    async def get_all_store_loads(self, store_id: int = None) -> list:
        if store_id:
            load_info = await self.get_store_load_info(store_id)
            if not load_info:
                raise NotFoundError("门店不存在或未启用")
            return [load_info]

        stores = await Store.objects.filter(status=True).all()
        result = []
        for store in stores:
            info = await self.get_store_load_info(store.id)
            if info:
                result.append(info)

        result.sort(key=lambda x: x["waiting_count"], reverse=True)
        return result


transfer_service = TransferService()
