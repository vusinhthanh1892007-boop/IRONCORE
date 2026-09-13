from ironcore.tui.i18n import i18n
import secrets
import threading
import re
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Input, Button, Switch, RadioSet, RadioButton
from textual.containers import Vertical, Horizontal
from ironcore.tui.screens.base import BaseWizardScreen
from ironcore.tui.runtime_client import (
    delete_google_maps_key,
    fetch_google_maps_key_status,
    save_google_maps_key,
)


_GOOGLE_MAPS_KEY_RE = re.compile(r"^AIza[0-9A-Za-z_-]{20,}$")

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

            yield Label(i18n.t("\nGoogle Maps API Key (optional):"))
            yield Input(
                placeholder=i18n.t("Enter Google Maps API key (AIza...)") ,
                password=True,
                id="google-maps-key",
            )
            yield Label(i18n.t("Google Maps key status: checking..."), id="maps-key-status")
            with Horizontal():
                yield Button(i18n.t("Save Maps Key"), id="btn-save-maps-key", variant="primary")
                yield Button(i18n.t("Delete Maps Key"), id="btn-delete-maps-key", variant="warning")
                yield Button(i18n.t("Refresh Key Status"), id="btn-refresh-maps-key", variant="default")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_mount(self) -> None:
        self._maps_has_key = False
        self._refresh_maps_status_async()

    def _set_maps_status(self, text: str) -> None:
        self.query_one("#maps-key-status", Label).update(text)

    def _clear_maps_input(self) -> None:
        self.query_one("#google-maps-key", Input).value = ""

    def _refresh_maps_status_async(self) -> None:
        threading.Thread(target=self._refresh_maps_status_bg, daemon=True).start()

    def _refresh_maps_status_bg(self) -> None:
        try:
            payload = fetch_google_maps_key_status()
            has_key = bool(payload.get("has_key", False))
            masked = str(payload.get("masked_key") or "")
            self._maps_has_key = has_key
            status_text = f"Google Maps key status: {'saved' if has_key else 'not saved'}"
            if has_key and masked:
                status_text = f"{status_text} · {masked}"
            self.app.call_from_thread(self._set_maps_status, status_text)
        except Exception:
            try:
                self.app.call_from_thread(self._set_maps_status, "Google Maps key status: unavailable")
            except Exception:
                pass

    def _save_maps_key_async(self, api_key: str) -> None:
        def _bg() -> None:
            try:
                payload = save_google_maps_key(api_key)
                self._maps_has_key = bool(payload.get("has_key", False))
                masked = str(payload.get("masked_key") or "")
                text = f"Google Maps key status: {'saved' if self._maps_has_key else 'not saved'}"
                if masked:
                    text = f"{text} · {masked}"
                self.app.call_from_thread(self._set_maps_status, text)
                self.app.call_from_thread(self._clear_maps_input)
            except Exception:
                try:
                    self.app.call_from_thread(self._set_maps_status, "Google Maps key status: save failed")
                except Exception:
                    pass

        threading.Thread(target=_bg, daemon=True).start()

    def _delete_maps_key_async(self) -> None:
        def _bg() -> None:
            try:
                payload = delete_google_maps_key()
                self._maps_has_key = bool(payload.get("has_key", False))
                self.app.call_from_thread(self._set_maps_status, "Google Maps key status: not saved")
            except Exception:
                try:
                    self.app.call_from_thread(self._set_maps_status, "Google Maps key status: delete failed")
                except Exception:
                    pass

        threading.Thread(target=_bg, daemon=True).start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ["btn-back", "btn-next"]:
            super().on_button_pressed(event)
            return

        if event.button.id == "btn-refresh-maps-key":
            self._set_maps_status("Google Maps key status: checking...")
            self._refresh_maps_status_async()
            return

        if event.button.id == "btn-save-maps-key":
            raw = self.query_one("#google-maps-key", Input).value.strip()
            if not raw:
                self.notify(i18n.t("Google Maps API key cannot be empty."), severity="error")
                return
            if not _GOOGLE_MAPS_KEY_RE.match(raw):
                self.notify(i18n.t("Invalid Google Maps API key format."), severity="error")
                return
            self._set_maps_status("Google Maps key status: saving...")
            self._save_maps_key_async(raw)
            return

        if event.button.id == "btn-delete-maps-key":
            self._set_maps_status("Google Maps key status: deleting...")
            self._delete_maps_key_async()
            return

    def on_next(self) -> None:
        if not self.query_one("#ack-token", Switch).value:
            self.notify(i18n.t("You must confirm that you saved the token to proceed."), title="Warning", severity="warning")
            return
        self.app.cfg["secret_token"] = "present" # Do not store plain text
        self.app.cfg["google_maps"] = {"api_key_present": bool(getattr(self, "_maps_has_key", False))}
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
