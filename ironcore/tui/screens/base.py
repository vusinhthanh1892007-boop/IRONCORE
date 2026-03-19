from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Button
from textual.containers import Horizontal
from ironcore.tui.i18n import i18n

class BaseWizardScreen(Screen):
    """Base class for all wizard screens to handle standard layouts and navigation."""
    
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+q", "app.quit", "Quit")
    ]
    
    def compose_navigation(self) -> ComposeResult:
        with Horizontal(classes="wizard-nav"):
            yield Button("Back", id="btn-back", variant="default")
            yield Button("Next", id="btn-next", variant="primary")
            
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(None)
        elif event.button.id == "btn-next":
            self.on_next()
            
    def on_next(self) -> None:
        """Override this to handle next logic and validation."""
        self.dismiss(True)
