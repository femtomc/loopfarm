from __future__ import annotations

import io

import pytest


@pytest.fixture
def stdout() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def stderr() -> io.StringIO:
    return io.StringIO()
