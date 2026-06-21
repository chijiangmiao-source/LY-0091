import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.transfer_service import TransferService
from app.exceptions import (
    ValidationError,
    NotFoundError,
    StateConflictError,
)
from app.models import (
    TRANSFER_STATUS,
    TRANSFER_SOURCE,
    STORE_LOAD_LEVEL,
)


@pytest.fixture
def service():
    return TransferService()


@pytest.fixture
def mock_transfer():
    transfer = MagicMock()
    transfer.id = 1
    transfer.transfer_no = "TR20240101001"
    transfer.status = TRANSFER_STATUS["pending_customer"]
    transfer.source_type = TRANSFER_SOURCE["queue"]
    transfer.source_record_id = 100
    transfer.source_store_id = 1
    transfer.target_store_id = 2
    transfer.phone = "13800138000"
    transfer.dict = MagicMock(return_value={
        "id": 1,
        "transfer_no": "TR20240101001",
        "status": TRANSFER_STATUS["pending_customer"],
        "source_type": TRANSFER_SOURCE["queue"],
    })
    return transfer


class TestTransferServiceStoreLoad:

    @pytest.mark.asyncio
    async def test_store_load_levels(self, service):
        with patch("app.services.transfer_service.Store") as MockStore:
            mock_store = MagicMock()
            mock_store.id = 1
            mock_store.name = "测试门店"
            MockStore.objects.get_or_none = AsyncMock(return_value=mock_store)
            with patch("app.services.transfer_service.FittingRoom") as MockRoom:
                MockRoom.objects.filter = MagicMock()
                MockRoom.objects.filter.return_value.count = AsyncMock(return_value=10)
                with patch("app.services.transfer_service.QueueRecord") as MockQueue:
                    MockQueue.objects.filter = MagicMock()
                    MockQueue.objects.filter.return_value.order_by = MagicMock()
                    MockQueue.objects.filter.return_value.order_by.return_value.count = AsyncMock(return_value=0)
                    info = await service.get_store_load_info(1)
                    assert info["store_id"] == 1
                    assert "level" in info
                    assert info["level"] in STORE_LOAD_LEVEL


class TestTransferServiceRecommendation:

    @pytest.mark.asyncio
    async def test_recommend_without_source_raises(self, service):
        with pytest.raises(ValidationError):
            await service.recommend_target_stores(
                source_store_id=None,
                room_type="standard",
            )


class TestTransferServiceStateTransitions:

    @pytest.mark.asyncio
    async def test_customer_confirm_nonexistent_raises(self, service):
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=None
            )
            with pytest.raises(NotFoundError):
                await service.customer_confirm_transfer(999, True)

    @pytest.mark.asyncio
    async def test_customer_confirm_already_confirmed_raises(self, service, mock_transfer):
        mock_transfer.status = TRANSFER_STATUS["customer_confirmed"]
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_transfer
            )
            with pytest.raises(StateConflictError):
                await service.customer_confirm_transfer(1, True)

    @pytest.mark.asyncio
    async def test_customer_confirm_already_rejected_raises(self, service, mock_transfer):
        mock_transfer.status = TRANSFER_STATUS["customer_rejected"]
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_transfer
            )
            with pytest.raises(StateConflictError):
                await service.customer_confirm_transfer(1, True)

    @pytest.mark.asyncio
    async def test_target_accept_wrong_state_raises(self, service, mock_transfer):
        mock_transfer.status = TRANSFER_STATUS["pending_customer"]
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_transfer
            )
            with pytest.raises(StateConflictError):
                await service.target_store_accept_transfer(1, True, None, None)

    @pytest.mark.asyncio
    async def test_execute_wrong_state_raises(self, service, mock_transfer):
        mock_transfer.status = TRANSFER_STATUS["pending_customer"]
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_transfer
            )
            with pytest.raises(StateConflictError):
                await service.execute_transfer(mock_transfer, None)

    @pytest.mark.asyncio
    async def test_cancel_already_executed_raises(self, service, mock_transfer):
        mock_transfer.status = TRANSFER_STATUS["completed"]
        with patch("app.services.transfer_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.select_related = MagicMock()
            MockTransfer.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_transfer
            )
            with pytest.raises(StateConflictError):
                await service.cancel_transfer(1, "测试取消")
