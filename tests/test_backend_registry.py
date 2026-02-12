from __future__ import annotations

import pytest

from loopfarm.backends import registry


class DummyBackend:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> registry:
    monkeypatch.setattr(registry, "_BACKENDS", {})
    return registry


def test_register_backend_rejects_empty_name(empty_registry: registry) -> None:
    with pytest.raises(ValueError, match="backend name cannot be empty"):
        empty_registry.register_backend(DummyBackend(""))


def test_register_backend_rejects_duplicates(empty_registry: registry) -> None:
    first = DummyBackend("demo")
    empty_registry.register_backend(first)
    empty_registry.register_backend(first)

    with pytest.raises(ValueError, match="backend already registered: demo"):
        empty_registry.register_backend(DummyBackend("demo"))


def test_list_backends_sorted(empty_registry: registry) -> None:
    empty_registry.register_backend(DummyBackend("beta"))
    empty_registry.register_backend(DummyBackend("alpha"))
    assert empty_registry.list_backends() == ["alpha", "beta"]


def test_get_backend_unknown_includes_available(empty_registry: registry) -> None:
    empty_registry.register_backend(DummyBackend("alpha"))
    with pytest.raises(KeyError, match=r"unknown backend 'missing'"):
        empty_registry.get_backend("missing")
