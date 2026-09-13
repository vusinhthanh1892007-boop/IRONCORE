import sys
import subprocess
import json
from pathlib import Path

def _ensure_deps():
    try:
        import textual
    except ImportError:
        print("[ IronCore ] Setup missing critical dependency (textual).")
        print("[ IronCore ] Please run: pip install textual")
        raise SystemExit(1)

_ensure_deps()

from textual.app import App
from ironcore.tui.i18n import i18n
from ironcore.tui.screens.language import LanguageScreen
from ironcore.tui.screens.preflight import PreflightScreen
from ironcore.tui.screens.auth_search import AuthScreen, SearchProviderScreen
from ironcore.tui.screens.models import ModelProvidersScreen, ModelPickerScreen
from ironcore.tui.screens.channels import ChannelScreen
from ironcore.tui.screens.features import SkillsScreen, HooksScreen, GatewayScreen
from ironcore.tui.screens.system import SecretsScreen, PersonaScreen, MonitoringScreen
from ironcore.tui.screens.final import FinalSmokeTestScreen, SummaryExportScreen
from ironcore.tui.lang_sync import TUILanguageSyncClient

class IronCoreTUI(App):
    CSS = """
    #content-container, #lang-container {
        padding: 1 4;
        height: 100%;
    }
    #step-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $primary;
        color: $text;
        width: 100%;
        margin-bottom: 1;
    }
    .wizard-nav {
        height: auto;
        margin-top: 2;
    }
    #btn-next { margin-left: 2; }
    .hidden { display: none; }
    .code-preview { margin: 1 0; padding: 1; background: $surface; }
    """
    
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.cfg = {}
        self._language_sync = TUILanguageSyncClient()
        self._route_history: list[str] = []
        self._route_map = {
            "language": LanguageScreen,
            "preflight": PreflightScreen,
            "auth": AuthScreen,
            "search": SearchProviderScreen,
            "providers": ModelProvidersScreen,
            "model_picker": ModelPickerScreen,
            "channels": ChannelScreen,
            "skills": SkillsScreen,
            "hooks": HooksScreen,
            "gateway": GatewayScreen,
            "secrets": SecretsScreen,
            "persona": PersonaScreen,
            "monitoring": MonitoringScreen,
            "final": FinalSmokeTestScreen,
            "deploy": SummaryExportScreen,
        }

    def _push_route(self, route: str, record_history: bool = True) -> None:
        screen_cls = self._route_map.get(route)
        if screen_cls is None:
            return

        self.push_screen(screen_cls(), self.handle_screen_result)
        if record_history:
            self._route_history.append(route)

    def on_mount(self) -> None:
        self._language_sync.start(self)
        self._push_route("language", record_history=True)

    def fallback_to_wizard_root(self) -> None:
        self._route_history = []
        self._push_route("language", record_history=True)

    def handle_screen_result(self, result: str) -> None:
        if result is None:
            # Back/dismiss callback path.
            # This wizard uses callback-driven transitions where previous screens
            # are dismissed. So we cannot rely on textual stack pop only.
            # We restore previous route from explicit history.
            if self._route_history:
                self._route_history.pop()

            if self._route_history:
                previous = self._route_history[-1]
                self._push_route(previous, record_history=False)
            else:
                self.fallback_to_wizard_root()
            return

        if not isinstance(result, str):
            return

        if len(result) == 2: # Language code (e.g. 'en')
            self.notify(f"Language set to: {i18n.current_lang}", title="Info")
            self._push_route("preflight", record_history=True)
        elif result in self._route_map:
            self._push_route(result, record_history=True)
        elif result == "done":
            self.exit(self.cfg)

if __name__ == "__main__":
    app = IronCoreTUI()
    cfg = app.run()
    if cfg:
        print("\\n[ IronCore ] Setup Completed Successfully!")
        print(f"Final Configuration Saved: {len(cfg)} keys applied.")
