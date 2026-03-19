import sys
import subprocess
import json
from pathlib import Path

def _ensure_deps():
    try:
        import textual
        import pycountry
    except ImportError:
        print("[ IronCore ] Installing Textual TUI dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "textual", "pycountry"],
            stdout=subprocess.DEVNULL,
        )

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

    def on_mount(self) -> None:
        self.push_screen(LanguageScreen(), self.handle_screen_result)

    def handle_screen_result(self, result: str) -> None:
        if result is None:
            # Back button pressed (pop screen). Handled gracefully by popping,
            # but textually we dismiss, so app receives None.
            # Usually we don't need to do anything as app.pop_screen is bound to ESC/Back
            return

        if len(result) == 2: # Language code (e.g. 'en')
            self.notify(f"Language set to: {i18n.current_lang}", title="Info")
            self.push_screen(PreflightScreen(), self.handle_screen_result)
        elif result == "auth":
            self.push_screen(AuthScreen(), self.handle_screen_result)
        elif result == "search":
            self.push_screen(SearchProviderScreen(), self.handle_screen_result)
        elif result == "providers":
            self.push_screen(ModelProvidersScreen(), self.handle_screen_result)
        elif result == "model_picker":
            self.push_screen(ModelPickerScreen(), self.handle_screen_result)
        elif result == "channels":
            self.push_screen(ChannelScreen(), self.handle_screen_result)
        elif result == "skills":
            self.push_screen(SkillsScreen(), self.handle_screen_result)
        elif result == "hooks":
            self.push_screen(HooksScreen(), self.handle_screen_result)
        elif result == "gateway":
            self.push_screen(GatewayScreen(), self.handle_screen_result)
        elif result == "secrets":
            self.push_screen(SecretsScreen(), self.handle_screen_result)
        elif result == "persona":
            self.push_screen(PersonaScreen(), self.handle_screen_result)
        elif result == "monitoring":
            self.push_screen(MonitoringScreen(), self.handle_screen_result)
        elif result == "final":
            self.push_screen(FinalSmokeTestScreen(), self.handle_screen_result)
        elif result == "deploy":
            self.push_screen(SummaryExportScreen(), self.handle_screen_result)
        elif result == "done":
            self.exit(self.cfg)

if __name__ == "__main__":
    app = IronCoreTUI()
    cfg = app.run()
    if cfg:
        print("\\n[ IronCore ] Setup Completed Successfully!")
        print(f"Final Configuration Saved: {len(cfg)} keys applied.")
