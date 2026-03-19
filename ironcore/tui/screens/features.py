from ironcore.tui.i18n import i18n
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, SelectionList, Input, Switch, RadioSet, RadioButton
from textual.widgets.selection_list import Selection
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen

class SkillsScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Skills & Plugins"), id="step-title")
            yield Label(i18n.t("Enable skills for your AI Agent:\n"))
            
            yield SelectionList(
                Selection(i18n.t("Web Search (API Key Needed)"), "web_search", True),
                Selection(i18n.t("Code Execution (Docker Sandbox)"), "code_exec"),
                Selection(i18n.t("Stealth Browser (Playwright)"), "browser"),
                Selection(i18n.t("Long-term Memory (ChromaDB)"), "memory"),
                Selection(i18n.t("Human-in-the-Loop (HITL)"), "hitl"),
                Selection(i18n.t("RAG / File Q&A"), "rag"),
                Selection(i18n.t("Voice STT/TTS"), "voice"),
                id="skills-list"
            )
            
            yield Label(i18n.t("\nMissing dependencies will be auto-installed."))
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
            yield Label(i18n.t("Hooks & Automation"), id="step-title")
            yield Label(i18n.t("Configure webhook events (e.g., on_message, on_error)"))
            
            with Horizontal():
                yield Switch(id="enable-webhooks")
                yield Label(i18n.t("  Enable Webhooks"))
                
            yield Input(placeholder=i18n.t("Webhook URL (e.g. https://your-server/hook)"), id="webhook-url", classes="hidden")
            yield Input(placeholder=i18n.t("Webhook HMAC Secret (blank for no signature)"), id="webhook-secret", password=True, classes="hidden")
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
        url = self.query_one("#webhook-url", Input).value.strip()
        secret = self.query_one("#webhook-secret", Input).value
        
        if enabled and not url.startswith("http"):
            self.notify(i18n.t("Webhook URL must start with http:// or https://"), severity="error")
            return
            
        self.app.cfg["hooks"] = {"enabled": enabled, "url": url, "has_secret": bool(secret)}
        self.dismiss("gateway")

class GatewayScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Gateway & Runtime Server"), id="step-title")
            
            yield Label(i18n.t("Port:"))
            yield Input("8000", id="gateway-port")
            
            yield Label(i18n.t("\nBind Interface:"))
            with RadioSet(id="gateway-bind"):
                yield RadioButton(i18n.t("127.0.0.1 (Loopback - Local only)"), id="bind-local", value=True)
                yield RadioButton(i18n.t("0.0.0.0 (Public - Expose to network)"), id="bind-public")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        port = self.query_one("#gateway-port", Input).value.strip()
        if not port.isdigit():
            self.notify(i18n.t("Gateway Port must be a valid number!"), severity="error")
            return
            
        bind = self.query_one("#gateway-bind", RadioSet).pressed_button.id
        self.app.cfg["gateway"] = {"port": port, "bind": bind}
        self.dismiss("secrets")
