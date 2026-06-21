import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.stats_service import StatsService


@pytest.fixture
def service():
    return StatsService()


class TestStatsServiceOverview:

    @pytest.mark.asyncio
    async def test_overview_returns_dict(self, service):
        with patch("app.services.stats_service.QueueRecord") as MockQueue:
            MockQueue.objects.filter = MagicMock()
            MockQueue.objects.filter.return_value.count = AsyncMock(return_value=0)
            MockQueue.objects.filter.return_value.select_related = MagicMock()
            MockQueue.objects.filter.return_value.select_related.return_value.all = AsyncMock(return_value=[])
            with patch("app.services.stats_service.Appointment") as MockAppt:
                MockAppt.objects.filter = MagicMock()
                MockAppt.objects.filter.return_value.count = AsyncMock(return_value=0)
                MockAppt.objects.filter.return_value.select_related = MagicMock()
                MockAppt.objects.filter.return_value.select_related.return_value.all = AsyncMock(return_value=[])
                result = await service.get_overview(days=7)
        assert isinstance(result, dict)
        assert "queue" in result
        assert "appointment" in result


class TestStatsServiceHourly:

    @pytest.mark.asyncio
    async def test_hourly_returns_24_hours(self, service):
        with patch("app.services.stats_service.QueueRecord") as MockQueue:
            MockQueue.objects.filter = MagicMock()
            MockQueue.objects.filter.return_value.select_related = MagicMock()
            MockQueue.objects.filter.return_value.select_related.return_value.all = AsyncMock(return_value=[])
            result = await service.get_hourly_stats(days=7)
        assert len(result) == 24
        assert all("hour" in h for h in result)


class TestStatsServiceDaily:

    @pytest.mark.asyncio
    async def test_daily_matches_days(self, service):
        days = 7
        with patch("app.services.stats_service.QueueRecord") as MockQueue:
            MockQueue.objects.filter = MagicMock()
            MockQueue.objects.filter.return_value.select_related = MagicMock()
            MockQueue.objects.filter.return_value.select_related.return_value.all = AsyncMock(return_value=[])
            result = await service.get_daily_stats(days=days)
        assert len(result) == days


class TestStatsServiceTransfer:

    @pytest.mark.asyncio
    async def test_transfer_overview(self, service):
        with patch("app.services.stats_service.StoreTransfer") as MockTransfer:
            MockTransfer.objects.filter = MagicMock()
            MockTransfer.objects.filter.return_value.count = AsyncMock(return_value=0)
            MockTransfer.objects.filter.return_value.select_related = MagicMock()
            MockTransfer.objects.filter.return_value.select_related.return_value.all = AsyncMock(return_value=[])
            result = await service.get_transfer_overview(days=7)
        assert isinstance(result, dict)
        assert "total" in result
