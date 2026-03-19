import secrets
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Input, Button, Switch, RadioSet, RadioButton
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen

class SecretsScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Token & Secrets", id="step-title")
            yield Label("Gateway Access Token generated. Save this securely!")
            
            token = secrets.token_urlsafe(32)
            masked = token[:4] + "*"*16 + token[-4:]
            self.raw_token = token
            
            yield Label(f"\n[bold yellow]{masked}[/]\n", id="masked-token")
            # Usually we add a copy button, but Textual can use pyperclip externally
            
            yield Label("Please confirm you have copied or written down the token:")
            with Horizontal():
                yield Switch(id="ack-token")
                yield Label("  I have saved the token")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        if not self.query_one("#ack-token", Switch).value:
            self.notify("You must confirm that you saved the token to proceed.", title="Warning", severity="warning")
            return
        self.app.cfg["secret_token"] = "present" # Do not store plain text
        self.dismiss("persona")

class PersonaScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Agent Persona (Hatch)", id="step-title")
            
            yield Label("Agent Name:")
            yield Input(placeholder="e.g. IronCore", id="persona-name")
            
            yield Label("System Prompt:")
            yield Input(placeholder="You are an expert autonomous AI agent...", id="persona-prompt")
            
            yield Label("Memory Policy:")
            with RadioSet(id="memory-policy"):
                yield RadioButton("Session (Forget after chat)", id="session")
                yield RadioButton("Persistent (SQLite Storage)", id="persistent", value=True)
                yield RadioButton("Summary (Compressed short-term)", id="summary")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        self.app.cfg["persona"] = {
            "name": self.query_one("#persona-name", Input).value,
            "prompt": self.query_one("#persona-prompt", Input).value,
            "memory": self.query_one("#memory-policy", RadioSet).pressed_button.id
        }
        self.dismiss("monitoring")

class MonitoringScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Monitoring & Backup", id="step-title")
            
            with Horizontal():
                yield Switch(id="telemetry", value=True)
                yield Label(" Enable Telemetry & Audit Logs")
                
            yield Label("\nBackup Strategy:")
            with RadioSet(id="backup-strategy"):
                yield RadioButton("Daily Snapshots", id="daily", value=True)
                yield RadioButton("Weekly", id="weekly")
                yield RadioButton("None", id="none")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        self.app.cfg["monitoring"] = {
            "telemetry": self.query_one("#telemetry", Switch).value,
            "backup": self.query_one("#backup-strategy", RadioSet).pressed_button.id
        }
        self.dismiss("final")
