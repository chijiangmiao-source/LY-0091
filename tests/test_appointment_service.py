import pytest
from datetime import datetime, timedelta, date
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.appointment_service import AppointmentService
from app.exceptions import (
    ValidationError,
    NotFoundError,
    StateConflictError,
)
from app.models import (
    APPOINTMENT_STATUS,
    DEFAULT_TIME_SLOTS,
    MAX_FUTURE_APPOINTMENT_DAYS,
)


@pytest.fixture
def service():
    return AppointmentService()


@pytest.fixture
def mock_appointment():
    appt = MagicMock()
    appt.id = 1
    appt.appointment_no = "YY20240101001"
    appt.phone = "13800138000"
    appt.customer_name = "测试顾客"
    appt.appointment_date = date.today()
    appt.time_slot = "10:00-11:00"
    appt.status = APPOINTMENT_STATUS["pending"]
    appt.dict = MagicMock(return_value={
        "id": 1,
        "appointment_no": "YY20240101001",
        "phone": "13800138000",
        "customer_name": "测试顾客",
        "status": APPOINTMENT_STATUS["pending"],
    })
    return appt


class TestAppointmentServiceNoGenerator:

    @pytest.mark.asyncio
    async def test_generate_no_format(self, service):
        with patch("app.services.appointment_service.Appointment") as MockAppt:
            MockAppt.objects.filter = MagicMock()
            MockAppt.objects.filter.return_value.count = AsyncMock(return_value=0)
            no = await service.generate_appointment_no()
            assert no.startswith("YY")
            today_str = datetime.now().strftime("%Y%m%d")
            assert today_str in no


class TestAppointmentServiceCreate:

    @pytest.mark.asyncio
    async def test_create_without_phone_raises(self, service):
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="",
                appointment_date="2024-12-01",
                time_slot="10:00-11:00",
            )

    @pytest.mark.asyncio
    async def test_create_without_date_raises(self, service):
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="13800138000",
                appointment_date="",
                time_slot="10:00-11:00",
            )

    @pytest.mark.asyncio
    async def test_create_without_slot_raises(self, service):
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="13800138000",
                appointment_date="2024-12-01",
                time_slot="",
            )

    @pytest.mark.asyncio
    async def test_create_past_date_raises(self, service):
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="13800138000",
                appointment_date=yesterday,
                time_slot="10:00-11:00",
            )

    @pytest.mark.asyncio
    async def test_create_too_far_future_raises(self, service):
        future = (date.today() + timedelta(days=MAX_FUTURE_APPOINTMENT_DAYS + 1)).strftime("%Y-%m-%d")
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="13800138000",
                appointment_date=future,
                time_slot="10:00-11:00",
            )

    @pytest.mark.asyncio
    async def test_create_invalid_slot_raises(self, service):
        future = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        with pytest.raises(ValidationError):
            await service.create_appointment(
                phone="13800138000",
                appointment_date=future,
                time_slot="25:00-26:00",
            )


class TestAppointmentServiceStateTransitions:

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_raises(self, service):
        with patch("app.services.appointment_service.Appointment") as MockAppt:
            MockAppt.objects.select_related = MagicMock()
            MockAppt.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=None
            )
            with pytest.raises(NotFoundError):
                await service.confirm_appointment(999)

    @pytest.mark.asyncio
    async def test_confirm_cancelled_raises(self, service, mock_appointment):
        mock_appointment.status = APPOINTMENT_STATUS["cancelled"]
        with patch("app.services.appointment_service.Appointment") as MockAppt:
            MockAppt.objects.select_related = MagicMock()
            MockAppt.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_appointment
            )
            with pytest.raises(StateConflictError):
                await service.confirm_appointment(1)

    @pytest.mark.asyncio
    async def test_confirm_already_confirmed_raises(self, service, mock_appointment):
        mock_appointment.status = APPOINTMENT_STATUS["confirmed"]
        with patch("app.services.appointment_service.Appointment") as MockAppt:
            MockAppt.objects.select_related = MagicMock()
            MockAppt.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_appointment
            )
            with pytest.raises(StateConflictError):
                await service.confirm_appointment(1)

    @pytest.mark.asyncio
    async def test_cancel_already_confirmed_raises(self, service, mock_appointment):
        mock_appointment.status = APPOINTMENT_STATUS["confirmed"]
        with patch("app.services.appointment_service.Appointment") as MockAppt:
            MockAppt.objects.select_related = MagicMock()
            MockAppt.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_appointment
            )
            with pytest.raises(StateConflictError):
                await service.cancel_appointment(1, "测试原因")


class TestAppointmentServiceSlots:

    @pytest.mark.asyncio
    async def test_get_date_range(self, service):
        result = await service.get_date_range()
        assert "start_date" in result
        assert "end_date" in result
        assert "max_days" in result
        assert len(result["dates"]) == MAX_FUTURE_APPOINTMENT_DAYS
