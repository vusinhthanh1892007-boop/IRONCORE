import platform
import socket
import sys
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Static, Markdown
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen
from ironcore.tui.i18n import i18n

class PreflightScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Welcome & Preflight Check"), id="step-title")
            yield Markdown(i18n.t(
                "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n"
                "  * Model providers & API keys\n"
                "  * Gateway service & Memory policy\n"
                "  * Agent persona & Hooks\n\n"
                "_Estimated time: 3-5 minutes_"
            ))
            
            with Vertical(classes="status-box"):
                py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                yield Label(f"{i18n.t('🖥  OS:')} {platform.system()}")
                yield Label(f"{i18n.t('🐍 Python:')} {py_ver} " + (" [green]✓[/]" if sys.version_info >= (3,10) else "[red]✗[/]"))
                
                net_ok = self.check_network()
                yield Label(f"{i18n.t('🌐 Network:')} " + (i18n.t("[green]Online ✓[/]") if net_ok else i18n.t("[red]Offline ✗[/]")))
            
            yield from self.compose_navigation()
        yield Footer()

    def check_network(self) -> bool:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except OSError:
            return False

    def on_next(self) -> None:
        self.app.cfg["preflight"] = {"os": platform.system(), "network_ok": self.check_network()}
        self.dismiss("auth")
