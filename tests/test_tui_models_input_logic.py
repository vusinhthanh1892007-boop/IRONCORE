import pytest

pytest.importorskip("textual")

from types import SimpleNamespace

from ironcore.tui.screens.models import ModelProvidersScreen


class _DummyProviderList:
    def __init__(self, selected):
        self.selected = selected


class _DummyInput:
    def __init__(self, value: str):
        self.value = value


def test_model_providers_on_next_saves_provider_key_presence(monkeypatch):
    screen = ModelProvidersScreen()
    fake_app = SimpleNamespace(cfg={})
    monkeypatch.setattr(ModelProvidersScreen, "app", property(lambda self: fake_app))

    mapping = {
        "#provider-list": _DummyProviderList(["openai", "xai"]),
        "#provider-key": _DummyInput("sk-live-123"),
    }

    monkeypatch.setattr(screen, "query_one", lambda selector, *_: mapping[selector])

    dismissed = []
    monkeypatch.setattr(screen, "dismiss", lambda result=None: dismissed.append(result))

    screen.on_next()

    assert fake_app.cfg["providers"] == ["openai", "xai"]
    assert fake_app.cfg["provider_key_present"] is True
    assert dismissed == ["model_picker"]


def test_model_providers_on_next_requires_selection(monkeypatch):
    screen = ModelProvidersScreen()
    fake_app = SimpleNamespace(cfg={})
    monkeypatch.setattr(ModelProvidersScreen, "app", property(lambda self: fake_app))

    mapping = {
        "#provider-list": _DummyProviderList([]),
        "#provider-key": _DummyInput("sk-live-123"),
    }

    monkeypatch.setattr(screen, "query_one", lambda selector, *_: mapping[selector])

    notifications = []
    dismissed = []
    monkeypatch.setattr(screen, "notify", lambda *args, **kwargs: notifications.append((args, kwargs)))
    monkeypatch.setattr(screen, "dismiss", lambda result=None: dismissed.append(result))

    screen.on_next()

    assert "providers" not in fake_app.cfg
    assert "provider_key_present" not in fake_app.cfg
    assert notifications, "Expected validation error notification when no provider selected"
    assert dismissed == []
