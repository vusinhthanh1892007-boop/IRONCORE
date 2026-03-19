from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, SelectionList, Input, Switch
from textual.widgets.selection_list import Selection
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen

class SkillsScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Skills & Plugins", id="step-title")
            yield Label("Enable skills for your AI Agent:\n")
            
            yield SelectionList(
                Selection("Web Search (API Key Needed)", "web_search", True),
                Selection("Code Execution (Docker Sandbox)", "code_exec"),
                Selection("Stealth Browser (Playwright)", "browser"),
                Selection("Long-term Memory (ChromaDB)", "memory"),
                Selection("Human-in-the-Loop (HITL)", "hitl"),
                Selection("RAG / File Q&A", "rag"),
                Selection("Voice STT/TTS", "voice"),
                id="skills-list"
            )
            
            yield Label("\nMissing dependencies will be auto-installed.")
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        sel = self.query_one("#skills-list", SelectionList).selected
        self.app.cfg["skills"] = sel
        self.dismiss("hooks")

class HooksScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Hooks & Automation", id="step-title")
            yield Label("Configure webhook events (e.g., on_message, on_error)")
            
            with Horizontal():
                yield Switch(id="enable-webhooks")
                yield Label("  Enable Webhooks")
                
            yield Input(placeholder="Webhook URL (e.g. https://your-server/hook)", id="webhook-url", classes="hidden")
            yield Input(placeholder="Webhook HMAC Secret (blank for no signature)", id="webhook-secret", password=True, classes="hidden")
            yield from self.compose_navigation()
        yield Footer()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        url = self.query_one("#webhook-url", Input)
        sec = self.query_one("#webhook-secret", Input)
        if event.value:
            url.remove_class("hidden")
            sec.remove_class("hidden")
        else:
            url.add_class("hidden")
            sec.add_class("hidden")

    def on_next(self) -> None:
        enabled = self.query_one("#enable-webhooks", Switch).value
        url = self.query_one("#webhook-url", Input).value
        secret = self.query_one("#webhook-secret", Input).value
        self.app.cfg["hooks"] = {"enabled": enabled, "url": url, "has_secret": bool(secret)}
        self.dismiss("gateway")

class GatewayScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Gateway & Runtime Server", id="step-title")
            
            yield Label("Port:")
            yield Input("8000", id="gateway-port")
            
            yield Label("\nBind Interface:")
            from textual.widgets import RadioSet, RadioButton
            with RadioSet(id="gateway-bind"):
                yield RadioButton("127.0.0.1 (Loopback - Local only)", id="127.0.0.1", value=True)
                yield RadioButton("0.0.0.0 (Public - Expose to network)", id="0.0.0.0")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        port = self.query_one("#gateway-port", Input).value
        bind = self.query_one("#gateway-bind", RadioSet).pressed_button.id
        self.app.cfg["gateway"] = {"port": port, "bind": bind}
        self.dismiss("secrets")
