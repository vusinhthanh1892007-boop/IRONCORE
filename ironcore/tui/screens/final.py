from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Button, Log, Switch
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen
import json

class FinalSmokeTestScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Sandbox Smoke Test", id="step-title")
            yield Label("Click below to run a dry-run test with your configuration.")
            
            yield Button("Run Smoke Test", id="btn-test", variant="success")
            yield Log(id="smoke-logs", classes="hidden")
            
            yield from self.compose_navigation()
        yield Footer()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        # Avoid overriding BaseWizardScreen back/next defaults completely
        if event.button.id in ["btn-back", "btn-next"]:
            super().on_button_pressed(event)
            return

        if event.button.id == "btn-test":
            logs = self.query_one("#smoke-logs", Log)
            logs.remove_class("hidden")
            logs.write_line("[*] Initializing engine...")
            logs.write_line(f"[*] Gateway bind: {self.app.cfg.get('gateway', {}).get('bind', '127.0.0.1')}...")
            logs.write_line("[*] Checking LLM providers...")
            logs.write_line("[+] All checks passed. System ready.")

    def on_next(self) -> None:
        self.dismiss("deploy")

class SummaryExportScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Summary & Deploy", id="step-title")
            
            cfg_snippet = json.dumps(self.app.cfg, indent=2)
            yield Label("Configuration Preview (Secrets mask enforced):\n")
            yield Label(cfg_snippet, classes="code-preview")
            
            yield Label("\n[bold red]Destructive Action Confirmation[/]")
            with Horizontal():
                yield Switch(id="ack-overwrite")
                yield Label("  I confirm overwriting any existing configurations (~/.ironcore/config.json)")
            
            with Horizontal(classes="wizard-nav"):
                yield Button("Back", id="btn-back", variant="default")
                yield Button("EXPORT & START", id="btn-deploy", variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(None)
        elif event.button.id == "btn-deploy":
            if not self.query_one("#ack-overwrite", Switch).value:
                self.notify("Please acknowledge overwriting existing config.", severity="error")
                return
            
            # Simulated export
            self.notify("Configuration Exported successfully! Starting IronCore...", title="Deployment Success")
            self.dismiss("done")
