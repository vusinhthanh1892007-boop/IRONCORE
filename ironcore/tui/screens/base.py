from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Button
from textual.containers import Horizontal
from ironcore.tui.i18n import i18n

class BaseWizardScreen(Screen):
    """Base class for all wizard screens to handle standard layouts and navigation."""

    show_back_button = True
    
    BINDINGS = [
        ("escape", "back", "Back"),
        ("ctrl+q", "app.quit", "Quit")
    ]

    def action_back(self) -> None:
        self.safe_dismiss(None)
    
    def compose_navigation(self) -> ComposeResult:
        with Horizontal(classes="wizard-nav"):
            if self.show_back_button:
                yield Button(i18n.t("Back"), id="btn-back", variant="default")
            yield Button(i18n.t("Next"), id="btn-next", variant="primary")
            
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.safe_dismiss(None)
        elif event.button.id == "btn-next":
            self.on_next()
            
    def on_next(self) -> None:
        """Override this to handle next logic and validation."""
        self.safe_dismiss(True)

    def safe_dismiss(self, result=None) -> None:
        if getattr(self, "_dismiss_handled", False):
            return
        self._dismiss_handled = True

        try:
            self.dismiss(result)
            return
        except Exception:
            pass

        app = getattr(self, "app", None)
        handler = getattr(app, "handle_screen_result", None)

        if result is None:
            pop_screen = getattr(app, "pop_screen", None)
            if callable(pop_screen):
                try:
                    pop_screen()
                    return
                except Exception:
                    pass

            fallback_to_wizard_root = getattr(app, "fallback_to_wizard_root", None)
            if callable(fallback_to_wizard_root):
                fallback_to_wizard_root()
                return

            self._dismiss_handled = False
            return

        if result is not None and callable(handler):
            handler(result)
            return

        self._dismiss_handled = False
