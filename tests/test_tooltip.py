"""Tests for tooltip layout helpers."""

from unittest import mock

from tokencounter.tooltip import get_startup_banner_position


class TestStartupBannerPosition:
    def test_starts_below_center_with_zero_alpha(self):
        with mock.patch("tokencounter.tooltip.get_screen_rect", return_value=(0, 0, 1920, 1080)):
            x, y, alpha = get_startup_banner_position(280, 62, progress=0.0)

        assert x == 820
        assert y == 527
        assert alpha == 0

    def test_ends_centered_and_opaque(self):
        with mock.patch("tokencounter.tooltip.get_screen_rect", return_value=(0, 0, 1920, 1080)):
            x, y, alpha = get_startup_banner_position(280, 62, progress=1.0)

        assert x == 820
        assert y == 509
        assert alpha == 255

