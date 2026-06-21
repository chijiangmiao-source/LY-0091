import falcon

from app.exceptions import BusinessError
from app.services import appointment_service
from app.models import (
    APPOINTMENT_STATUS, ROOM_TYPES, DEFAULT_TIME_SLOTS,
    get_no_show_count_with_penalty
)


async def generate_appointment_no():
    return await appointment_service.generate_appointment_no()


async def process_expired_appointments():
    return await appointment_service.process_expired_appointments()


class AppointmentListResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        status = req.get_param("status")
        phone = req.get_param("phone")
        appointment_date = req.get_param("appointment_date")
        page = req.get_param_as_int("page") or 1
        page_size = req.get_param_as_int("page_size") or 20

        try:
            result = await appointment_service.list_appointments(
                store_id=store_id, status=status, phone=phone,
                appointment_date=appointment_date, page=page, page_size=page_size
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        try:
            result = await appointment_service.create_appointment(
                phone=(data.get("phone") or "").strip(),
                appointment_date=(data.get("appointment_date") or "").strip(),
                time_slot=(data.get("time_slot") or "").strip(),
                room_type=(data.get("room_type") or "standard").strip(),
                customer_name=data.get("customer_name"),
                store_id=data.get("store_id"),
                verify_code=data.get("verify_code"),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "预约成功", "data": result}


class AppointmentDetailResource:
    async def on_get(self, req, resp, appointment_id):
        try:
            data = await appointment_service.get_appointment_detail(appointment_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": data}

    async def on_delete(self, req, resp, appointment_id):
        try:
            data = await req.get_media()
            cancel_reason = (data or {}).get("cancel_reason", "用户主动取消")
        except Exception:
            cancel_reason = "用户主动取消"

        try:
            await appointment_service.cancel_appointment(appointment_id, cancel_reason)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "取消预约成功"}


class AppointmentConfirmResource:
    async def on_post(self, req, resp, appointment_id):
        try:
            result = await appointment_service.confirm_appointment(appointment_id)
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "核销成功，已转入排队", "data": result}


class AppointmentSlotsResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        appointment_date = req.get_param("appointment_date")
        room_type = req.get_param("room_type") or "standard"

        try:
            result = await appointment_service.get_available_slots(
                store_id=store_id, appointment_date=appointment_date, room_type=room_type
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class AppointmentDateRangeResource:
    async def on_get(self, req, resp):
        try:
            result = await appointment_service.get_date_range()
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}


class AppointmentStatusResource:
    async def on_get(self, req, resp):
        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": [{"value": k, "label": v} for k, v in APPOINTMENT_STATUS.items()]
        }


class AppointmentCheckNoShowResource:
    async def on_get(self, req, resp):
        phone = req.get_param("phone")
        if not phone:
            raise falcon.HTTPBadRequest(title="参数错误", description="手机号不能为空")

        result = await get_no_show_count_with_penalty(phone)
        resp.media = {"code": 0, "message": "获取成功", "data": result}


class AppointmentProcessExpiredResource:
    async def on_post(self, req, resp):
        await process_expired_appointments()
        resp.media = {"code": 0, "message": "过期预约处理完成"}


class AppointmentSlotConfigResource:
    async def on_get(self, req, resp):
        store_id = req.get_param_as_int("store_id")
        room_type = req.get_param("room_type")

        try:
            result = await appointment_service.list_slot_configs(
                store_id=store_id, room_type=room_type
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "获取成功", "data": result}

    async def on_post(self, req, resp):
        try:
            data = await req.get_media()
        except Exception:
            raise falcon.HTTPBadRequest(title="请求错误", description="无效的JSON数据")

        try:
            result = await appointment_service.save_slot_config(
                store_id=data.get("store_id"),
                room_type=(data.get("room_type") or "standard").strip(),
                time_slot=(data.get("time_slot") or "").strip(),
                capacity=data.get("capacity") or 5,
                is_active=data.get("is_active", True),
            )
        except BusinessError as e:
            raise e.to_http()

        resp.media = {"code": 0, "message": "保存成功", "data": result}
