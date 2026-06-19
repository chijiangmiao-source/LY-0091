from app.routes.auth import LoginResource, UserInfoResource
from app.routes.store import StoreListResource, StoreDetailResource, FloorListResource
from app.routes.fitting_room import (
    FittingRoomListResource, FittingRoomDetailResource,
    FittingRoomCleanResource, FittingRoomStatusResource
)
from app.routes.queue import (
    QueueListResource, QueueDetailResource,
    QueueCallResource, QueueEnterResource, QueueLeaveResource,
    QueueOvertimeResource, QueueRequeueResource,
    QueueWaitingListResource, QueueStatusResource
)
from app.routes.lost_item import (
    LostItemListResource, LostItemDetailResource,
    LostItemSealResource, LostItemClaimResource,
    LostItemDisposeResource, LostItemStatusResource
)
from app.routes.stats import (
    StatsOverviewResource, StatsHourlyResource,
    StatsStoreResource, StatsDailyResource
)
from app.routes.pages import (
    LoginPageResource, DashboardPageResource,
    StoresPageResource, FittingRoomsPageResource,
    QueuePageResource, LostItemsPageResource, StatsPageResource
)

__all__ = [
    "LoginResource", "UserInfoResource",
    "StoreListResource", "StoreDetailResource", "FloorListResource",
    "FittingRoomListResource", "FittingRoomDetailResource",
    "FittingRoomCleanResource", "FittingRoomStatusResource",
    "QueueListResource", "QueueDetailResource",
    "QueueCallResource", "QueueEnterResource", "QueueLeaveResource",
    "QueueOvertimeResource", "QueueRequeueResource",
    "QueueWaitingListResource", "QueueStatusResource",
    "LostItemListResource", "LostItemDetailResource",
    "LostItemSealResource", "LostItemClaimResource",
    "LostItemDisposeResource", "LostItemStatusResource",
    "StatsOverviewResource", "StatsHourlyResource",
    "StatsStoreResource", "StatsDailyResource",
    "LoginPageResource", "DashboardPageResource",
    "StoresPageResource", "FittingRoomsPageResource",
    "QueuePageResource", "LostItemsPageResource", "StatsPageResource",
]
