from ironcore.tui.i18n import i18n
import secrets
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Input, Button, Switch, RadioSet, RadioButton
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen

class SecretsScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Token & Secrets"), id="step-title")
            yield Label(i18n.t("Gateway Access Token generated. Save this securely!"))
            
            token = secrets.token_urlsafe(32)
            masked = token[:4] + "*"*16 + token[-4:]
            self.raw_token = token
            
            yield Label(f"\n[bold yellow]{masked}[/]\n", id="masked-token")
            # Usually we add a copy button, but Textual can use pyperclip externally
            
            yield Label(i18n.t("Please confirm you have copied or written down the token:"))
            with Horizontal():
                yield Switch(id="ack-token")
                yield Label(i18n.t("  I have saved the token"))
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        if not self.query_one("#ack-token", Switch).value:
            self.notify(i18n.t("You must confirm that you saved the token to proceed."), title="Warning", severity="warning")
            return
        self.app.cfg["secret_token"] = "present" # Do not store plain text
        self.safe_dismiss("persona")

class PersonaScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Agent Persona (Hatch)"), id="step-title")
            
            yield Label(i18n.t("Agent Name:"))
            yield Input(placeholder=i18n.t("e.g. IronCore"), id="persona-name")
            
            yield Label(i18n.t("System Prompt:"))
            yield Input(placeholder=i18n.t("You are an expert autonomous AI agent..."), id="persona-prompt")
            
            yield Label(i18n.t("Memory Policy:"))
            with RadioSet(id="memory-policy"):
                yield RadioButton(i18n.t("Session (Forget after chat)"), id="session")
                yield RadioButton(i18n.t("Persistent (SQLite Storage)"), id="persistent", value=True)
                yield RadioButton(i18n.t("Summary (Compressed short-term)"), id="summary")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        self.app.cfg["persona"] = {
            "name": self.query_one("#persona-name", Input).value,
            "prompt": self.query_one("#persona-prompt", Input).value,
            "memory": self.query_one("#memory-policy", RadioSet).pressed_button.id
        }
        self.safe_dismiss("monitoring")

class MonitoringScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Monitoring & Backup"), id="step-title")
            
            with Horizontal():
                yield Switch(id="telemetry", value=True)
                yield Label(i18n.t(" Enable Telemetry & Audit Logs"))
                
            yield Label(i18n.t("\nBackup Strategy:"))
            with RadioSet(id="backup-strategy"):
                yield RadioButton(i18n.t("Daily Snapshots"), id="daily", value=True)
                yield RadioButton(i18n.t("Weekly"), id="weekly")
                yield RadioButton(i18n.t("None"), id="none")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        self.app.cfg["monitoring"] = {
            "telemetry": self.query_one("#telemetry", Switch).value,
            "backup": self.query_one("#backup-strategy", RadioSet).pressed_button.id
        }
        self.safe_dismiss("final")
