import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.queue_service import QueueService
from app.exceptions import (
    ValidationError,
    NotFoundError,
    StateConflictError,
)
from app.models import QUEUE_STATUS, QUEUE_SOURCE


@pytest.fixture
def service():
    return QueueService()


@pytest.fixture
def mock_queue_record():
    record = MagicMock()
    record.id = 1
    record.ticket_number = "A001"
    record.phone = "13800138000"
    record.customer_name = "测试顾客"
    record.status = QUEUE_STATUS["waiting"]
    record.source = QUEUE_SOURCE["on_site"]
    record.created_at = datetime.now()
    record.dict = MagicMock(return_value={
        "id": 1,
        "ticket_number": "A001",
        "phone": "13800138000",
        "customer_name": "测试顾客",
        "status": QUEUE_STATUS["waiting"],
        "source": QUEUE_SOURCE["on_site"],
    })
    return record


class TestQueueServiceTicketNumber:

    @pytest.mark.asyncio
    async def test_generate_ticket_number_format(self, service):
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.filter = MagicMock()
            MockRecord.objects.filter.return_value.count = AsyncMock(return_value=0)
            ticket = await service.generate_ticket_number(store_id=1)
            today_str = datetime.now().strftime("%Y%m%d")
            assert ticket.startswith(today_str)
            assert ticket.endswith("001")

    @pytest.mark.asyncio
    async def test_generate_ticket_number_increment(self, service):
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.filter = MagicMock()
            MockRecord.objects.filter.return_value.count = AsyncMock(return_value=5)
            ticket = await service.generate_ticket_number(store_id=1)
            assert ticket.endswith("006")


class TestQueueServiceCreate:

    @pytest.mark.asyncio
    async def test_create_without_phone_raises(self, service):
        with pytest.raises(ValidationError):
            await service.create_queue_record(
                phone="",
                store_id=1,
            )

    @pytest.mark.asyncio
    async def test_create_without_store_raises(self, service):
        with pytest.raises(ValidationError):
            await service.create_queue_record(
                phone="13800138000",
                store_id=None,
            )


class TestQueueServiceStateTransitions:

    @pytest.mark.asyncio
    async def test_call_called_record_raises(self, service, mock_queue_record):
        mock_queue_record.status = QUEUE_STATUS["called"]
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_queue_record
            )
            with pytest.raises(StateConflictError):
                await service.call_queue(1)

    @pytest.mark.asyncio
    async def test_call_completed_record_raises(self, service, mock_queue_record):
        mock_queue_record.status = QUEUE_STATUS["completed"]
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_queue_record
            )
            with pytest.raises(StateConflictError):
                await service.call_queue(1)

    @pytest.mark.asyncio
    async def test_call_nonexistent_raises(self, service):
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=None
            )
            with pytest.raises(NotFoundError):
                await service.call_queue(999)

    @pytest.mark.asyncio
    async def test_enter_non_called_raises(self, service, mock_queue_record):
        mock_queue_record.status = QUEUE_STATUS["waiting"]
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_queue_record
            )
            with pytest.raises(StateConflictError):
                await service.enter_room(1, None)

    @pytest.mark.asyncio
    async def test_leave_non_entered_raises(self, service, mock_queue_record):
        mock_queue_record.status = QUEUE_STATUS["called"]
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_queue_record
            )
            with pytest.raises(StateConflictError):
                await service.leave_room(1)

    @pytest.mark.asyncio
    async def test_mark_overtime_non_called_raises(self, service, mock_queue_record):
        mock_queue_record.status = QUEUE_STATUS["waiting"]
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.select_related = MagicMock()
            MockRecord.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_queue_record
            )
            with pytest.raises(StateConflictError):
                await service.mark_overtime(1)


class TestQueueServiceFairStrategy:

    @pytest.mark.asyncio
    async def test_fair_strategy_empty_queue(self, service):
        with patch("app.services.queue_service.QueueRecord") as MockRecord:
            MockRecord.objects.filter = MagicMock()
            MockRecord.objects.filter.return_value.order_by = MagicMock()
            MockRecord.objects.filter.return_value.order_by.return_value.first = AsyncMock(
                return_value=None
            )
            result = await service.get_fair_next_record(store_id=1)
            assert result is None
