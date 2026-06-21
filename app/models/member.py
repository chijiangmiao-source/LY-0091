import ormar
from datetime import datetime
from typing import Optional
from app.config import MainMeta
from app.models.user import User


MEMBER_TAG_DEFINITIONS = {
    "high_frequency": {"name": "高频到店", "color": "blue", "description": "近30天到店5次及以上"},
    "easy_no_show": {"name": "易爽约", "color": "red", "description": "近30天爽约2次及以上"},
    "vip": {"name": "VIP顾客", "color": "purple", "description": "近90天到店10次及以上且爽约率低于10%"},
    "lost_item_risk": {"name": "遗留物高风险", "color": "orange", "description": "近90天遗留物事件2次及以上"},
    "frequent_overtime": {"name": "频繁过号", "color": "yellow", "description": "近30天过号2次及以上"},
    "gray_list": {"name": "灰名单", "color": "gray", "description": "存在风险行为但未达到黑名单标准"},
    "black_list": {"name": "黑名单", "color": "black", "description": "严重违规或多次爽约被封禁"},
}

BLACKLIST_STATUS = {
    "black": "黑名单",
    "gray": "灰名单",
    "normal": "正常",
}

BLACKLIST_REASON = {
    "no_show_exceed": "爽约次数超标",
    "manual": "人工标记",
    "abnormal_behavior": "异常行为",
    "lost_item_risk": "遗留物高风险",
    "other": "其他原因",
}


class MemberProfile(ormar.Model):
    class Meta(MainMeta):
        tablename = "member_profiles"

    id: int = ormar.Integer(primary_key=True)
    phone: str = ormar.String(max_length=20, unique=True, index=True)
    customer_name: str = ormar.String(max_length=50, nullable=True)
    blacklist_status: str = ormar.String(max_length=20, default="normal")
    blacklist_reason: str = ormar.String(max_length=200, nullable=True)
    blacklist_at: Optional[datetime] = ormar.DateTime(nullable=True)
    blacklist_by: Optional[User] = ormar.ForeignKey(User, related_name="blacklist_ops", nullable=True)
    unblacklist_at: Optional[datetime] = ormar.DateTime(nullable=True)
    unblacklist_by: Optional[User] = ormar.ForeignKey(User, related_name="unblacklist_ops", nullable=True)
    unblacklist_reason: str = ormar.String(max_length=200, nullable=True)
    total_visits: int = ormar.Integer(default=0)
    total_no_shows: int = ormar.Integer(default=0)
    total_overtimes: int = ormar.Integer(default=0)
    total_lost_items: int = ormar.Integer(default=0)
    total_appointments: int = ormar.Integer(default=0)
    last_visit_at: Optional[datetime] = ormar.DateTime(nullable=True)
    tags: str = ormar.Text(default="")
    remark: str = ormar.String(max_length=500, nullable=True)
    created_at: datetime = ormar.DateTime(default=datetime.now)
    updated_at: datetime = ormar.DateTime(default=datetime.now)

    def get_tags_list(self) -> list:
        if not self.tags:
            return []
        return [t for t in self.tags.split(",") if t]

    def set_tags_list(self, tag_keys: list):
        self.tags = ",".join(tag_keys)

    def get_blacklist_status_text(self) -> str:
        return BLACKLIST_STATUS.get(self.blacklist_status, self.blacklist_status)

    def is_blocked(self) -> bool:
        return self.blacklist_status == "black"

    def is_gray(self) -> bool:
        return self.blacklist_status == "gray"


class MemberBehavior(ormar.Model):
    class Meta(MainMeta):
        tablename = "member_behaviors"

    id: int = ormar.Integer(primary_key=True)
    phone: str = ormar.String(max_length=20, index=True)
    member: Optional[MemberProfile] = ormar.ForeignKey(
        MemberProfile, related_name="behaviors", nullable=True
    )
    behavior_type: str = ormar.String(max_length=30)
    related_id: Optional[int] = ormar.Integer(nullable=True)
    store_name: str = ormar.String(max_length=100, nullable=True)
    detail: str = ormar.String(max_length=500, nullable=True)
    recorded_at: datetime = ormar.DateTime(default=datetime.now)
    recorded_by: Optional[User] = ormar.ForeignKey(User, related_name="recorded_behaviors", nullable=True)


BEHAVIOR_TYPES = {
    "fitting": "试衣",
    "appointment": "预约",
    "no_show": "爽约",
    "overtime": "过号",
    "lost_item": "遗留物",
    "claim": "认领登记",
    "blacklist_add": "加入黑名单",
    "blacklist_remove": "移出黑名单",
    "graylist_add": "加入灰名单",
    "graylist_remove": "移出灰名单",
    "intercept": "黑名单拦截",
    "transfer_out": "跨店转出",
    "transfer_in": "跨店转入",
    "transfer_customer_confirm": "转单顾客确认",
    "transfer_customer_reject": "转单顾客拒绝",
    "transfer_completed": "转单完成",
    "transfer_failed": "转单失败",
}


class BlacklistLog(ormar.Model):
    class Meta(MainMeta):
        tablename = "blacklist_logs"

    id: int = ormar.Integer(primary_key=True)
    phone: str = ormar.String(max_length=20, index=True)
    member: Optional[MemberProfile] = ormar.ForeignKey(
        MemberProfile, related_name="blacklist_logs", nullable=True
    )
    action: str = ormar.String(max_length=30)
    reason: str = ormar.String(max_length=200, nullable=True)
    operator: Optional[User] = ormar.ForeignKey(User, related_name="blacklist_log_ops", nullable=True)
    operated_at: datetime = ormar.DateTime(default=datetime.now)
    intercept_scene: str = ormar.String(max_length=50, nullable=True)
    intercept_result: str = ormar.String(max_length=20, nullable=True)
    remark: str = ormar.String(max_length=500, nullable=True)


BLACKLIST_ACTIONS = {
    "add_black": "加入黑名单",
    "remove_black": "移出黑名单",
    "add_gray": "加入灰名单",
    "remove_gray": "移出灰名单",
    "intercept_appointment": "拦截预约",
    "intercept_queue": "拦截取号",
    "intercept_claim": "拦截认领",
    "pass_verify": "二次校验通过",
}
