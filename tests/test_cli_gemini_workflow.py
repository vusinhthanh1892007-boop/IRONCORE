import cli


def test_step_providers_google_with_api_key(monkeypatch):
    monkeypatch.setattr(cli, "_step", lambda *_args, **_kwargs: None)

    class _Ask:
        def __init__(self, value):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(cli.questionary, "checkbox", lambda *args, **kwargs: _Ask(["Google"]))
    monkeypatch.setattr(cli.questionary, "password", lambda *args, **kwargs: _Ask("dummy-google-key-1234"))

    cfg = cli.step_providers({})

    assert "providers" in cfg
    assert cfg["providers"]["Google"]["has_api_key"] is True
    assert cfg["providers"]["Google"]["key_masked"] == "dumm••••1234"


def test_step_model_picker_google_gemini(monkeypatch):
    monkeypatch.setattr(cli, "_step", lambda *_args, **_kwargs: None)

    class _Ask:
        def __init__(self, value):
            self._value = value

        def ask(self):
            return self._value

    picks = iter(["Google", "gemini-3.1-pro"])
    monkeypatch.setattr(cli.questionary, "select", lambda *args, **kwargs: _Ask(next(picks)))

    cfg = cli.step_model_picker({"providers": {"Google": {"has_api_key": True, "key_masked": "AIza••••1234"}}})

    assert cfg["selected_model"] == {"provider": "Google", "model_id": "gemini-3.1-pro"}


def test_step_smoke_test_marks_provider_config_present(monkeypatch):
    monkeypatch.setattr(cli, "_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.time, "sleep", lambda *_args, **_kwargs: None)

    cfg = cli.step_smoke_test({"providers": {"Google": {"has_api_key": False}}, "gateway": {"host": "127.0.0.1"}})

    assert cfg["smoke_test"]["total"] == 4
    assert cfg["smoke_test"]["passed"] == 4
