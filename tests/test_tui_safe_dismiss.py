from types import SimpleNamespace

from ironcore.tui.screens.base import BaseWizardScreen


class _DummyScreen(BaseWizardScreen):
    pass


def test_safe_dismiss_routes_result_when_pop_fails(monkeypatch):
    screen = _DummyScreen()

    routed = []
    fake_app = SimpleNamespace(handle_screen_result=lambda result: routed.append(result))
    monkeypatch.setattr(_DummyScreen, "app", property(lambda self: fake_app))

    monkeypatch.setattr(screen, "dismiss", lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("Can't pop screen")))

    screen.safe_dismiss("deploy")

    assert routed == ["deploy"]


def test_safe_dismiss_ignores_back_when_pop_fails(monkeypatch):
    screen = _DummyScreen()

    routed = []
    fake_app = SimpleNamespace(handle_screen_result=lambda result: routed.append(result))
    monkeypatch.setattr(_DummyScreen, "app", property(lambda self: fake_app))

    monkeypatch.setattr(screen, "dismiss", lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("Can't pop screen")))

    screen.safe_dismiss(None)

    assert routed == []
