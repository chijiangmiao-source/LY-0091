import falcon
import falcon.asgi
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import database, metadata, engine, APP_PORT
from app.middleware import AuthMiddleware, CORSMiddleware
from app.routes import (
    LoginResource, UserInfoResource,
    StoreListResource, StoreDetailResource, FloorListResource,
    FittingRoomListResource, FittingRoomDetailResource,
    FittingRoomCleanResource, FittingRoomStatusResource,
    QueueListResource, QueueDetailResource,
    QueueCallResource, QueueEnterResource, QueueLeaveResource,
    QueueOvertimeResource, QueueRequeueResource,
    QueueWaitingListResource, QueueStatusResource,
    QueueNextCallResource, QueueSourceResource, QueueAutoCallResource,
    LostItemListResource, LostItemDetailResource,
    LostItemSealResource, LostItemClaimResource,
    LostItemDisposeResource, LostItemStatusResource,
    StatsOverviewResource, StatsHourlyResource,
    StatsStoreResource, StatsDailyResource,
    StatsAppointmentResource, StatsAppointmentPeakResource,
    AppointmentListResource, AppointmentDetailResource,
    AppointmentConfirmResource, AppointmentSlotsResource,
    AppointmentDateRangeResource, AppointmentStatusResource,
    AppointmentCheckNoShowResource, AppointmentProcessExpiredResource,
    AppointmentSlotConfigResource,
    LoginPageResource, DashboardPageResource,
    StoresPageResource, FittingRoomsPageResource,
    QueuePageResource, LostItemsPageResource, StatsPageResource,
)


class StaticResource:
    async def on_get(self, req, resp, filename):
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "static")
        file_path = os.path.join(static_dir, filename)
        if not os.path.exists(file_path):
            raise falcon.HTTPNotFound()
        if filename.endswith(".css"):
            resp.content_type = "text/css; charset=utf-8"
        elif filename.endswith(".js"):
            resp.content_type = "application/javascript; charset=utf-8"
        elif filename.endswith(".png"):
            resp.content_type = "image/png"
        elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
            resp.content_type = "image/jpeg"
        else:
            resp.content_type = "application/octet-stream"
        with open(file_path, "rb") as f:
            resp.data = f.read()


class StartupMiddleware:
    def __init__(self):
        self._started = False

    async def process_startup(self, scope, event):
        if self._started:
            return
        self._started = True
        await database.connect()
        metadata.create_all(engine)
        print(f"✅ 数据库连接成功，服务启动于 http://0.0.0.0:{APP_PORT}")

    async def process_shutdown(self, scope, event):
        if self._started:
            await database.disconnect()
            print("✅ 数据库连接已关闭")


def create_app():
    app = falcon.asgi.App(
        middleware=[
            CORSMiddleware(),
            StartupMiddleware(),
            AuthMiddleware(exempt_paths=[
                "/login", "/api/login", "/static/", "/favicon.ico"
            ])
        ]
    )

    app.add_route("/", DashboardPageResource())
    app.add_route("/login", LoginPageResource())
    app.add_route("/stores", StoresPageResource())
    app.add_route("/fitting-rooms", FittingRoomsPageResource())
    app.add_route("/queue", QueuePageResource())
    app.add_route("/lost-items", LostItemsPageResource())
    app.add_route("/stats", StatsPageResource())

    app.add_route("/api/login", LoginResource())
    app.add_route("/api/user/info", UserInfoResource())

    app.add_route("/api/floors", FloorListResource())

    app.add_route("/api/stores", StoreListResource())
    app.add_route("/api/stores/{store_id:int}", StoreDetailResource())

    app.add_route("/api/fitting-rooms", FittingRoomListResource())
    app.add_route("/api/fitting-rooms/options", FittingRoomStatusResource())
    app.add_route("/api/fitting-rooms/{room_id:int}", FittingRoomDetailResource())
    app.add_route("/api/fitting-rooms/{room_id:int}/clean", FittingRoomCleanResource())

    app.add_route("/api/queue", QueueListResource())
    app.add_route("/api/queue/waiting", QueueWaitingListResource())
    app.add_route("/api/queue/status", QueueStatusResource())
    app.add_route("/api/queue/sources", QueueSourceResource())
    app.add_route("/api/queue/next-call", QueueNextCallResource())
    app.add_route("/api/queue/auto-call", QueueAutoCallResource())
    app.add_route("/api/queue/{record_id:int}", QueueDetailResource())
    app.add_route("/api/queue/{record_id:int}/call", QueueCallResource())
    app.add_route("/api/queue/{record_id:int}/enter", QueueEnterResource())
    app.add_route("/api/queue/{record_id:int}/leave", QueueLeaveResource())
    app.add_route("/api/queue/{record_id:int}/overtime", QueueOvertimeResource())
    app.add_route("/api/queue/{record_id:int}/requeue", QueueRequeueResource())

    app.add_route("/api/lost-items", LostItemListResource())
    app.add_route("/api/lost-items/status", LostItemStatusResource())
    app.add_route("/api/lost-items/{item_id:int}", LostItemDetailResource())
    app.add_route("/api/lost-items/{item_id:int}/seal", LostItemSealResource())
    app.add_route("/api/lost-items/{item_id:int}/claim", LostItemClaimResource())
    app.add_route("/api/lost-items/{item_id:int}/dispose", LostItemDisposeResource())

    app.add_route("/api/stats/overview", StatsOverviewResource())
    app.add_route("/api/stats/hourly", StatsHourlyResource())
    app.add_route("/api/stats/stores", StatsStoreResource())
    app.add_route("/api/stats/daily", StatsDailyResource())
    app.add_route("/api/stats/appointment", StatsAppointmentResource())
    app.add_route("/api/stats/appointment-peak", StatsAppointmentPeakResource())

    app.add_route("/api/appointments", AppointmentListResource())
    app.add_route("/api/appointments/slots", AppointmentSlotsResource())
    app.add_route("/api/appointments/dates", AppointmentDateRangeResource())
    app.add_route("/api/appointments/status", AppointmentStatusResource())
    app.add_route("/api/appointments/check-no-show", AppointmentCheckNoShowResource())
    app.add_route("/api/appointments/process-expired", AppointmentProcessExpiredResource())
    app.add_route("/api/appointments/slot-configs", AppointmentSlotConfigResource())
    app.add_route("/api/appointments/{appointment_id:int}", AppointmentDetailResource())
    app.add_route("/api/appointments/{appointment_id:int}/confirm", AppointmentConfirmResource())

    app.add_route("/static/{filename}", StaticResource())

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=APP_PORT,
        reload=False,
        lifespan="on"
    )
