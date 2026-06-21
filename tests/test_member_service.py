import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.member_service import MemberService
from app.exceptions import (
    BlacklistBlockedError,
    BlacklistGrayError,
    PenaltyBlockedError,
    ValidationError,
)
from app.models import (
    BLACKLIST_STATUS,
    NO_SHOW_THRESHOLD,
)


@pytest.fixture
def service():
    return MemberService()


@pytest.fixture
def mock_member():
    member = MagicMock()
    member.id = 1
    member.phone = "13800138000"
    member.customer_name = "测试顾客"
    member.blacklist_status = BLACKLIST_STATUS["normal"]
    member.tags = ""
    member.get_tags_list = MagicMock(return_value=[])
    member.get_blacklist_status_text = MagicMock(return_value="正常")
    return member


class TestMemberServiceCheckBlacklist:

    @pytest.mark.asyncio
    async def test_check_blacklist_normal_user(self, service, mock_member):
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            result = await service.check_blacklist("13800138000", "appointment")
            assert result["allowed"] is True
            assert result["status"] == "normal"

    @pytest.mark.asyncio
    async def test_check_blacklist_blocked_user(self, service, mock_member):
        mock_member.blacklist_status = BLACKLIST_STATUS["blocked"]
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            result = await service.check_blacklist("13800138000", "appointment")
            assert result["allowed"] is False
            assert result["status"] == "blocked"
            assert "blacklist" in result["message"]

    @pytest.mark.asyncio
    async def test_check_blacklist_gray_user(self, service, mock_member):
        mock_member.blacklist_status = BLACKLIST_STATUS["gray"]
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            result = await service.check_blacklist("13800138000", "appointment")
            assert result["allowed"] is False
            assert result["status"] == "gray"
            assert "verify" in result

    @pytest.mark.asyncio
    async def test_check_blacklist_no_show_penalty(self, service, mock_member):
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            with patch("app.services.member_service.get_no_show_count_with_penalty") as mock_no_show:
                mock_no_show.return_value = {
                    "count": NO_SHOW_THRESHOLD + 1,
                    "blocked": True,
                    "message": "7天内无法取号",
                }
                result = await service.check_blacklist("13800138000", "appointment")
                assert result["allowed"] is False
                assert "no_show" in result["message"]


class TestMemberServiceValidateBlacklist:

    @pytest.mark.asyncio
    async def test_validate_normal(self, service, mock_member):
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            result = await service.validate_blacklist_for_scene(
                "13800138000", "appointment", None, "取号"
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_blocked_raises(self, service, mock_member):
        mock_member.blacklist_status = BLACKLIST_STATUS["blocked"]
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            with pytest.raises(BlacklistBlockedError):
                await service.validate_blacklist_for_scene(
                    "13800138000", "appointment", None, "取号"
                )

    @pytest.mark.asyncio
    async def test_validate_gray_raises(self, service, mock_member):
        mock_member.blacklist_status = BLACKLIST_STATUS["gray"]
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            with pytest.raises(BlacklistGrayError):
                await service.validate_blacklist_for_scene(
                    "13800138000", "appointment", None, "取号"
                )

    @pytest.mark.asyncio
    async def test_validate_gray_with_code(self, service, mock_member):
        mock_member.blacklist_status = BLACKLIST_STATUS["gray"]
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            result = await service.validate_blacklist_for_scene(
                "13800138000", "appointment", "8888", "取号"
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_show_raises(self, service, mock_member):
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            with patch("app.services.member_service.get_no_show_count_with_penalty") as mock_no_show:
                mock_no_show.return_value = {
                    "count": NO_SHOW_THRESHOLD + 1,
                    "blocked": True,
                    "message": "7天内无法取号",
                }
                with pytest.raises(PenaltyBlockedError):
                    await service.validate_blacklist_for_scene(
                        "13800138000", "appointment", None, "取号"
                    )


class TestMemberServicePhoneValidation:

    @pytest.mark.asyncio
    async def test_empty_phone_raises(self, service):
        with pytest.raises(ValidationError):
            await service.check_blacklist("", "appointment")

    @pytest.mark.asyncio
    async def test_invalid_phone_raises(self, service):
        with pytest.raises(ValidationError):
            await service.get_or_create_member("12345")

    @pytest.mark.asyncio
    async def test_valid_phone(self, service):
        with patch("app.services.member_service.MemberProfile") as MockProfile:
            mock_member = MagicMock()
            mock_member.id = 1
            MockProfile.objects.get_or_none = AsyncMock(return_value=(mock_member, False))
            member = await service.get_or_create_member("13800138000")
            assert member.id == 1
