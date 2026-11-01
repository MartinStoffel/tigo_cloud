"""Fixtures for the Tigo Cloud tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

PANEL = {"A": 1, "B": 2, "C": "A1", "T": "T1"}
READINGS = {"pin": {"1": 100}, "day": 2000, "plan": "Free"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def tigo() -> Generator[None]:
    """Answer the Tigo requests without the cloud."""
    with (
        patch(
            "custom_components.tigo_cloud.tigo.TigoData.async_get_panels",
            return_value=[PANEL],
        ),
        patch(
            "custom_components.tigo_cloud.tigo.TigoData.fetch_data",
            return_value=READINGS,
        ),
    ):
        yield
