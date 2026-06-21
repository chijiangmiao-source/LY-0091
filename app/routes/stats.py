from app.exceptions import BusinessError
from app.services import stats_service


class StatsOverviewResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_overview(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsHourlyResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")

        try:
            data = await stats_service.get_hourly_stats(days, store_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsStoreResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_store_stats(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsDailyResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_daily_stats(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsPeakResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")

        try:
            data = await stats_service.get_peak_stats(days, store_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsHeatmapResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")

        try:
            data = await stats_service.get_heatmap(days, store_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsAppointmentOverviewResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_appointment_stats(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsAppointmentPeakResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_appointment_peak_stats(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsAppointmentSlotsResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")

        try:
            data = await stats_service.get_appointment_slot_stats(days, store_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsTransferOverviewResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_transfer_overview(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsTransferDailyResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_transfer_daily(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsTransferPeakHourResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_transfer_peak_hour(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsTransferStoreLoadResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_transfer_store_load(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}


class StatsTransferHeatmapResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7

        try:
            data = await stats_service.get_transfer_heatmap(days)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}
