"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "importer"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


def make_response(
    body: str,
    *,
    status_code: int = 200,
    content_type: str = "text/html; charset=UTF-8",
) -> httpx.Response:
    """Build an httpx.Response as if returned by the importer, for detector tests."""
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": content_type},
        text=body,
        request=httpx.Request("GET", "http://importer/?automate=true&config=x.json"),
    )


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")
