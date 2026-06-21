import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.lost_item_service import LostItemService
from app.exceptions import (
    ValidationError,
    NotFoundError,
    StateConflictError,
)
from app.models import LOST_ITEM_STATUS


@pytest.fixture
def service():
    return LostItemService()


@pytest.fixture
def mock_lost_item():
    item = MagicMock()
    item.id = 1
    item.item_name = "手机"
    item.status = LOST_ITEM_STATUS["registered"]
    item.dict = MagicMock(return_value={
        "id": 1,
        "item_name": "手机",
        "status": LOST_ITEM_STATUS["registered"],
    })
    return item


class TestLostItemServiceRegister:

    @pytest.mark.asyncio
    async def test_register_without_name_raises(self, service):
        with pytest.raises(ValidationError):
            await service.register_lost_item(
                item_name="",
                fitting_room_id=1,
            )

    @pytest.mark.asyncio
    async def test_register_without_room_raises(self, service):
        with pytest.raises(ValidationError):
            await service.register_lost_item(
                item_name="手机",
                fitting_room_id=None,
            )


class TestLostItemServiceStateTransitions:

    @pytest.mark.asyncio
    async def test_seal_nonexistent_raises(self, service):
        with patch("app.services.lost_item_service.LostItem") as MockItem:
            MockItem.objects.select_related = MagicMock()
            MockItem.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=None
            )
            with pytest.raises(NotFoundError):
                await service.seal_lost_item(999, "储物柜A", None)

    @pytest.mark.asyncio
    async def test_seal_already_sealed_raises(self, service, mock_lost_item):
        mock_lost_item.status = LOST_ITEM_STATUS["sealed"]
        with patch("app.services.lost_item_service.LostItem") as MockItem:
            MockItem.objects.select_related = MagicMock()
            MockItem.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_lost_item
            )
            with pytest.raises(StateConflictError):
                await service.seal_lost_item(1, "储物柜A", None)

    @pytest.mark.asyncio
    async def test_claim_not_sealed_raises(self, service, mock_lost_item):
        mock_lost_item.status = LOST_ITEM_STATUS["registered"]
        with patch("app.services.lost_item_service.LostItem") as MockItem:
            MockItem.objects.select_related = MagicMock()
            MockItem.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_lost_item
            )
            with pytest.raises(StateConflictError):
                await service.claim_lost_item(
                    item_id=1,
                    claimant_name="张三",
                    claimant_phone="13800138000",
                    claimant_id_card="110101199001011234",
                    claim_user=None,
                )

    @pytest.mark.asyncio
    async def test_claim_already_claimed_raises(self, service, mock_lost_item):
        mock_lost_item.status = LOST_ITEM_STATUS["claimed"]
        with patch("app.services.lost_item_service.LostItem") as MockItem:
            MockItem.objects.select_related = MagicMock()
            MockItem.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_lost_item
            )
            with pytest.raises(StateConflictError):
                await service.claim_lost_item(
                    item_id=1,
                    claimant_name="张三",
                    claimant_phone="13800138000",
                    claimant_id_card="110101199001011234",
                    claim_user=None,
                )

    @pytest.mark.asyncio
    async def test_dispose_already_claimed_raises(self, service, mock_lost_item):
        mock_lost_item.status = LOST_ITEM_STATUS["claimed"]
        with patch("app.services.lost_item_service.LostItem") as MockItem:
            MockItem.objects.select_related = MagicMock()
            MockItem.objects.select_related.return_value.get_or_none = AsyncMock(
                return_value=mock_lost_item
            )
            with pytest.raises(StateConflictError):
                await service.dispose_lost_item(1, "超过保管期限")
