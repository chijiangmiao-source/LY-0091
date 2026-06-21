import falcon
from datetime import datetime, timedelta
from collections import defaultdict
from app.models import (
    MemberProfile, MemberBehavior, BlacklistLog, User,
    QueueRecord, Appointment, NoShowRecord, LostItem,
    MEMBER_TAG_DEFINITIONS, BLACKLIST_STATUS, BLACKLIST_REASON,
    BEHAVIOR_TYPES, BLACKLIST_ACTIONS
)


async def get_or_create_member(phone: str, customer_name: str = None) -> MemberProfile:
    member = await MemberProfile.objects.filter(phone=phone).first()
    if not member:
        member = MemberProfile(phone=phone, customer_name=customer_name)
        await member.save()
    elif customer_name and not member.customer_name:
        member.customer_name = customer_name
        await member.update()
    return member


async def record_behavior(phone: str, behavior_type: str, detail: str = None,
                          related_id: int = None, store_name: str = None,
                          user_id: int = None):
    member = await MemberProfile.objects.filter(phone=phone).first()
    behavior = MemberBehavior(
        phone=phone,
        member=member,
        behavior_type=behavior_type,
        related_id=related_id,
        store_name=store_name,
        detail=detail
    )
    if user_id:
        try:
            user = await User.objects.get(id=user_id)
            behavior.recorded_by = user
        except Exception:
            pass
    await behavior.save()
    return behavior


async def refresh_member_stats(phone: str):
    member = await MemberProfile.objects.filter(phone=phone).first()
    if not member:
        return

    now = datetime.now()
    days_30 = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    start_30 = now - timedelta(days=30)
    start_90 = now - timedelta(days=90)

    queue_records = await QueueRecord.objects.filter(phone=phone).all()
    entered_records = [r for r in queue_records if r.status in ["entered", "left"]]
    overtime_records = [r for r in queue_records if r.is_overtime]

    member.total_visits = len(entered_records)
    member.total_overtimes = len(overtime_records)

    no_show_records = await NoShowRecord.objects.filter(phone=phone).all()
    member.total_no_shows = len(no_show_records)

    lost_items_as_claimant = await LostItem.objects.filter(claimant_phone=phone).all()
    queue_ids = [r.id for r in queue_records]
    lost_items_in_room = []
    all_lost = await LostItem.objects.all()
    for li in all_lost:
        if li.queue_record and li.queue_record.id in queue_ids:
            lost_items_in_room.append(li)
    member.total_lost_items = len(lost_items_in_room) + len(lost_items_as_claimant)

    appointments = await Appointment.objects.filter(phone=phone).all()
    member.total_appointments = len(appointments)

    last_visit = None
    if entered_records:
        times = [r.enter_time for r in entered_records if r.enter_time]
        if times:
            last_visit = max(times)
    member.last_visit_at = last_visit

    await member.update()
    await refresh_member_tags(phone)
    return member


async def refresh_member_tags(phone: str):
    member = await MemberProfile.objects.filter(phone=phone).first()
    if not member:
        return

    now = datetime.now()
    start_30 = now - timedelta(days=30)
    start_90 = now - timedelta(days=90)
    tag_keys = []

    queue_30 = await QueueRecord.objects.filter(
        phone=phone,
        queue_time__gte=start_30,
        status__in=["entered", "left"]
    ).all()
    if len(queue_30) >= 5:
        tag_keys.append("high_frequency")

    no_show_30 = await NoShowRecord.objects.filter(
        phone=phone,
        recorded_at__gte=start_30
    ).all()
    if len(no_show_30) >= 2:
        tag_keys.append("easy_no_show")

    queue_90 = await QueueRecord.objects.filter(
        phone=phone,
        queue_time__gte=start_90,
        status__in=["entered", "left"]
    ).all()
    no_show_90 = await NoShowRecord.objects.filter(
        phone=phone,
        recorded_at__gte=start_90
    ).all()
    total_90 = len(queue_90) + len(no_show_90)
    if len(queue_90) >= 10 and (total_90 > 0 and len(no_show_90) / total_90 < 0.1):
        tag_keys.append("vip")

    all_queue = await QueueRecord.objects.filter(phone=phone).all()
    queue_ids = [r.id for r in all_queue]
    all_lost = await LostItem.objects.all()
    lost_count = 0
    for li in all_lost:
        if li.queue_record and li.queue_record.id in queue_ids:
            lost_count += 1
    lost_as_claimant = await LostItem.objects.filter(claimant_phone=phone).all()
    total_lost = lost_count + len(lost_as_claimant)
    if total_lost >= 2:
        tag_keys.append("lost_item_risk")

    overtime_30 = await QueueRecord.objects.filter(
        phone=phone,
        queue_time__gte=start_30,
        is_overtime=True
    ).all()
    if len(overtime_30) >= 2:
        tag_keys.append("frequent_overtime")

    if member.blacklist_status == "gray":
        tag_keys.append("gray_list")
    if member.blacklist_status == "black":
        tag_keys.append("black_list")

    old_tags = set(member.get_tags_list())
    new_tags = set(tag_keys)
    if old_tags != new_tags:
        member.set_tags_list(tag_keys)
        member.updated_at = datetime.now()
        await member.update()

    return tag_keys


async def check_blacklist(phone: str, scene: str = "appointment") -> dict:
    member = await MemberProfile.objects.filter(phone=phone).first()
    if not member:
        return {"is_blocked": False, "is_gray": False, "member": None}

    if member.is_blocked():
        await BlacklistLog(
            phone=phone,
            member=member,
            action=f"intercept_{scene}",
            intercept_scene=scene,
            intercept_result="blocked",
            remark=f"黑名单用户尝试{scene}被拦截"
        ).save()
        return {
            "is_blocked": True,
            "is_gray": False,
            "member": member,
            "reason": member.blacklist_reason or "该用户已被加入黑名单"
        }

    if member.is_gray():
        return {
            "is_blocked": False,
            "is_gray": True,
            "member": member,
            "reason": member.blacklist_reason or "该用户处于灰名单，需二次校验"
        }

    return {"is_blocked": False, "is_gray": False, "member": member}


class MemberListResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        blacklist_status = req.get_param("blacklist_status")
        tag = req.get_param("tag")
        keyword = req.get_param("keyword")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        query = MemberProfile.objects.select_related("blacklist_by", "unblacklist_by")

        if phone:
            query = query.filter(phone__contains=phone)
        if blacklist_status:
            query = query.filter(blacklist_status=blacklist_status)
        if keyword:
            query = query.filter(customer_name__contains=keyword)
        if tag:
            query = query.filter(tags__contains=tag)

        total = await query.count()
        records = await query.order_by("-updated_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for r in records:
            data = r.dict()
            data["tags_list"] = r.get_tags_list()
            data["tag_details"] = [
                {"key": t, **MEMBER_TAG_DEFINITIONS.get(t, {"name": t, "color": "default", "description": ""})}
                for t in r.get_tags_list()
            ]
            data["blacklist_status_text"] = r.get_blacklist_status_text()
            result.append(data)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": result
            }
        }


class MemberDetailResource:
    async def on_get(self, req, resp, member_id):
        try:
            member = await MemberProfile.objects.select_related("blacklist_by", "unblacklist_by").get(id=member_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="会员不存在")

        data = member.dict()
        data["tags_list"] = member.get_tags_list()
        data["tag_details"] = [
            {"key": t, **MEMBER_TAG_DEFINITIONS.get(t, {"name": t, "color": "default", "description": ""})}
            for t in member.get_tags_list()
        ]
        data["blacklist_status_text"] = member.get_blacklist_status_text()

        behaviors = await MemberBehavior.objects.filter(phone=member.phone).order_by("-recorded_at").limit(50).all()
        data["recent_behaviors"] = [
            {**b.dict(), "behavior_type_text": BEHAVIOR_TYPES.get(b.behavior_type, b.behavior_type)}
            for b in behaviors
        ]

        blacklist_logs = await BlacklistLog.objects.filter(phone=member.phone).order_by("-operated_at").limit(20).all()
        data["blacklist_logs"] = [
            {**l.dict(), "action_text": BLACKLIST_ACTIONS.get(l.action, l.action)}
            for l in blacklist_logs
        ]

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_put(self, req, resp, member_id):
        try:
            member = await MemberProfile.objects.get(id=member_id)
        except Exception:
            raise falcon.HTTPNotFound(title="未找到", description="会员不存在")

        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        if data.get("customer_name"):
            member.customer_name = data["customer_name"]
        if data.get("remark") is not None:
            member.remark = data["remark"]

        member.updated_at = datetime.now()
        await member.update()

        resp.media = {"code": 0, "message": "更新成功", "data": member.dict()}


class MemberPhoneResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        member = await get_or_create_member(phone)
        await refresh_member_stats(phone)

        member = await MemberProfile.objects.select_related("blacklist_by", "unblacklist_by").get(id=member.id)
        data = member.dict()
        data["tags_list"] = member.get_tags_list()
        data["tag_details"] = [
            {"key": t, **MEMBER_TAG_DEFINITIONS.get(t, {"name": t, "color": "default", "description": ""})}
            for t in member.get_tags_list()
        ]
        data["blacklist_status_text"] = member.get_blacklist_status_text()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class MemberRefreshResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            data = {}

        phone = data.get("phone")
        if phone:
            member = await refresh_member_stats(phone)
            if member:
                resp.media = {"code": 0, "message": "刷新成功", "data": member.dict()}
                return

        members = await MemberProfile.objects.all()
        count = 0
        for m in members:
            await refresh_member_stats(m.phone)
            count += 1

        resp.media = {"code": 0, "message": f"已刷新{count}个会员画像"}


class MemberBehaviorResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        behavior_type = req.get_param("behavior_type")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        query = MemberBehavior.objects.filter(phone=phone)
        if behavior_type:
            query = query.filter(behavior_type=behavior_type)

        total = await query.count()
        records = await query.order_by("-recorded_at").limit(page_size).offset((page - 1) * page_size).all()

        result = []
        for r in records:
            data = r.dict()
            data["behavior_type_text"] = BEHAVIOR_TYPES.get(r.behavior_type, r.behavior_type)
            result.append(data)

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": result
            }
        }

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        phone = (data.get("phone") or "").strip()
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        behavior_type = (data.get("behavior_type") or "").strip()
        if behavior_type not in BEHAVIOR_TYPES:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的行为类型")

        member = await get_or_create_member(phone, data.get("customer_name"))

        user_id = None
        if hasattr(req, 'context') and req.context.get("user"):
            user_id = req.context["user"].id

        behavior = await record_behavior(
            phone=phone,
            behavior_type=behavior_type,
            detail=data.get("detail"),
            related_id=data.get("related_id"),
            store_name=data.get("store_name"),
            user_id=user_id
        )

        await refresh_member_stats(phone)

        resp.media = {"code": 0, "message": "记录成功", "data": behavior.dict()}


class BlacklistManageResource:
    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        phone = (data.get("phone") or "").strip()
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        action = (data.get("action") or "").strip()
        if action not in ["add_black", "add_gray", "remove_black", "remove_gray"]:
            raise falcon.HTTPBadRequest(title="参数错误", description="无效的操作类型")

        reason = (data.get("reason") or "").strip()

        member = await get_or_create_member(phone, data.get("customer_name"))

        operator = None
        if hasattr(req, 'context') and req.context.get("user"):
            operator = req.context["user"]

        now = datetime.now()

        if action == "add_black":
            if member.is_blocked():
                raise falcon.HTTPBadRequest(title="操作失败", description="该用户已在黑名单中")
            member.blacklist_status = "black"
            member.blacklist_reason = reason or BLACKLIST_REASON.get("manual", "人工标记")
            member.blacklist_at = now
            member.blacklist_by = operator
            member.unblacklist_at = None
            member.unblacklist_by = None
            member.unblacklist_reason = None
        elif action == "add_gray":
            if member.is_gray():
                raise falcon.HTTPBadRequest(title="操作失败", description="该用户已在灰名单中")
            if member.is_blocked():
                raise falcon.HTTPBadRequest(title="操作失败", description="该用户在黑名单中，请先移出黑名单")
            member.blacklist_status = "gray"
            member.blacklist_reason = reason or BLACKLIST_REASON.get("manual", "人工标记")
            member.blacklist_at = now
            member.blacklist_by = operator
        elif action == "remove_black":
            if not member.is_blocked():
                raise falcon.HTTPBadRequest(title="操作失败", description="该用户不在黑名单中")
            member.blacklist_status = "normal"
            member.unblacklist_at = now
            member.unblacklist_by = operator
            member.unblacklist_reason = reason or "人工解除"
        elif action == "remove_gray":
            if not member.is_gray():
                raise falcon.HTTPBadRequest(title="操作失败", description="该用户不在灰名单中")
            member.blacklist_status = "normal"
            member.unblacklist_at = now
            member.unblacklist_by = operator
            member.unblacklist_reason = reason or "人工解除"

        member.updated_at = now
        await member.update()
        await refresh_member_tags(phone)

        log = BlacklistLog(
            phone=phone,
            member=member,
            action=action,
            reason=reason or BLACKLIST_REASON.get("manual", "人工标记"),
            operator=operator,
            remark=data.get("remark")
        )
        await log.save()

        behavior_type_map = {
            "add_black": "blacklist_add",
            "add_gray": "graylist_add",
            "remove_black": "blacklist_remove",
            "remove_gray": "graylist_remove",
        }
        await record_behavior(
            phone=phone,
            behavior_type=behavior_type_map[action],
            detail=f"{BLACKLIST_ACTIONS[action]}，原因：{reason or '人工标记'}",
            user_id=operator.id if operator else None
        )

        result = member.dict()
        result["tags_list"] = member.get_tags_list()
        result["blacklist_status_text"] = member.get_blacklist_status_text()

        resp.media = {"code": 0, "message": "操作成功", "data": result}


class BlacklistCheckResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        scene = req.get_param("scene") or "appointment"

        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        result = await check_blacklist(phone, scene)
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class MemberStatsResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 30
        start_date = datetime.now() - timedelta(days=days)

        total_members = await MemberProfile.objects.count()
        black_count = await MemberProfile.objects.filter(blacklist_status="black").count()
        gray_count = await MemberProfile.objects.filter(blacklist_status="gray").count()
        normal_count = total_members - black_count - gray_count

        active_30 = await MemberProfile.objects.filter(
            last_visit_at__gte=start_date
        ).count()

        all_members = await MemberProfile.objects.all()
        risk_distribution = {"low": 0, "medium": 0, "high": 0, "blocked": 0}
        for m in all_members:
            if m.is_blocked():
                risk_distribution["blocked"] += 1
            else:
                tags = m.get_tags_list()
                has_risk = any(t in tags for t in ["easy_no_show", "lost_item_risk", "frequent_overtime"])
                has_good = any(t in tags for t in ["high_frequency", "vip"])
                if has_risk:
                    risk_distribution["high"] += 1
                elif has_good:
                    risk_distribution["medium"] += 1
                else:
                    risk_distribution["low"] += 1

        intercept_logs = await BlacklistLog.objects.filter(
            operated_at__gte=start_date,
            action__startswith="intercept_"
        ).all()

        intercept_total = len(intercept_logs)
        intercept_by_scene = defaultdict(int)
        for il in intercept_logs:
            intercept_by_scene[il.intercept_scene or "unknown"] += 1

        intercept_by_day = defaultdict(int)
        for il in intercept_logs:
            day_key = il.operated_at.strftime("%Y-%m-%d")
            intercept_by_day[day_key] += 1

        pass_verify_count = await BlacklistLog.objects.filter(
            operated_at__gte=start_date,
            action="pass_verify"
        ).count()

        all_behaviors = await MemberBehavior.objects.filter(recorded_at__gte=start_date).all()
        behavior_by_type = defaultdict(int)
        for b in all_behaviors:
            behavior_by_type[b.behavior_type] += 1

        tag_distribution = defaultdict(int)
        for m in all_members:
            for t in m.get_tags_list():
                tag_distribution[t] += 1

        tag_stats = []
        for key, count in sorted(tag_distribution.items(), key=lambda x: -x[1]):
            tag_def = MEMBER_TAG_DEFINITIONS.get(key, {"name": key, "color": "default", "description": ""})
            tag_stats.append({
                "key": key,
                "name": tag_def.get("name", key),
                "color": tag_def.get("color", "default"),
                "count": count,
                "percentage": round(count / total_members * 100, 1) if total_members > 0 else 0
            })

        active_by_day = defaultdict(int)
        for b in all_behaviors:
            if b.behavior_type in ["fitting", "appointment"]:
                day_key = b.recorded_at.strftime("%Y-%m-%d")
                active_by_day[day_key] += 1

        daily_active = []
        for i in range(days):
            current_day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_active.append({
                "date": current_day,
                "active_count": active_by_day.get(current_day, 0)
            })

        daily_intercept = []
        for i in range(days):
            current_day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_intercept.append({
                "date": current_day,
                "intercept_count": intercept_by_day.get(current_day, 0)
            })

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "days": days,
                "overview": {
                    "total_members": total_members,
                    "black_count": black_count,
                    "gray_count": gray_count,
                    "normal_count": normal_count,
                    "active_30_count": active_30,
                    "active_rate": round(active_30 / total_members * 100, 1) if total_members > 0 else 0
                },
                "risk_distribution": risk_distribution,
                "tag_distribution": tag_stats,
                "intercept_stats": {
                    "total": intercept_total,
                    "pass_verify_count": pass_verify_count,
                    "by_scene": dict(intercept_by_scene),
                    "daily": daily_intercept
                },
                "behavior_stats": {
                    "by_type": {k: v for k, v in sorted(behavior_by_type.items(), key=lambda x: -x[1])}
                },
                "daily_active": daily_active
            }
        }


class MemberTagDefinitionsResource:
    async def on_get(self, req, resp):
        result = [
            {"key": k, **v}
            for k, v in MEMBER_TAG_DEFINITIONS.items()
        ]
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class BlacklistStatusOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BLACKLIST_STATUS.items()]
        }


class BehaviorTypeOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BEHAVIOR_TYPES.items()]
        }


class BlacklistReasonOptionsResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in BLACKLIST_REASON.items()]
        }
