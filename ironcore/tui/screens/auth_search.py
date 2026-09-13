from ironcore.tui.i18n import i18n
import threading
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Input, RadioSet, RadioButton, Button
from textual.containers import Vertical
from ironcore.tui.screens.base import BaseWizardScreen
from ironcore.tui.runtime_client import (
    list_token_profiles,
    revoke_token_profile,
    save_token_profile,
    use_token_profile,
)

class AuthScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Authentication"), id="step-title")
            yield Label(i18n.t("Select your authentication mode:"))
            
            with RadioSet(id="auth-mode"):
                yield RadioButton(i18n.t("Local only — no account, config saved to ~/.ironcore"), id="local", value=True)
                yield RadioButton(i18n.t("Cloud Token — sync settings across devices"), id="cloud")
                
            yield Input(placeholder=i18n.t("Paste your IronCore Cloud token..."), password=True, id="auth-token", classes="hidden")
            yield Input(placeholder=i18n.t("Token profile id (e.g. dev-cloud)"), id="auth-profile-id", classes="hidden")
            yield Input(placeholder=i18n.t("Scopes (comma-separated, e.g. chat.read,chat.write)"), id="auth-profile-scopes", classes="hidden")
            yield Input(placeholder=i18n.t("Expiry days (optional, e.g. 30)"), id="auth-profile-expiry", classes="hidden")
            yield Label(i18n.t("Token profiles: loading..."), id="auth-profile-status", classes="hidden")
            yield Button(i18n.t("Save Token Profile"), id="btn-token-save", variant="primary", classes="hidden")
            yield Button(i18n.t("Use Token Profile"), id="btn-token-use", variant="default", classes="hidden")
            yield Button(i18n.t("Revoke Token Profile"), id="btn-token-revoke", variant="warning", classes="hidden")
            yield Button(i18n.t("Refresh Profiles"), id="btn-token-refresh", variant="default", classes="hidden")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_profiles_async()

    def _set_profile_controls_hidden(self, hidden: bool) -> None:
        ids = [
            "#auth-token",
            "#auth-profile-id",
            "#auth-profile-scopes",
            "#auth-profile-expiry",
            "#auth-profile-status",
            "#btn-token-save",
            "#btn-token-use",
            "#btn-token-revoke",
            "#btn-token-refresh",
        ]
        for selector in ids:
            widget = self.query_one(selector)
            if hidden:
                widget.add_class("hidden")
            else:
                widget.remove_class("hidden")

    def _set_profile_status(self, text: str) -> None:
        self.query_one("#auth-profile-status", Label).update(text)

    def _set_auth_token_input(self, token: str) -> None:
        self.query_one("#auth-token", Input).value = token

    def _refresh_profiles_async(self) -> None:
        threading.Thread(target=self._refresh_profiles_bg, daemon=True).start()

    def _refresh_profiles_bg(self) -> None:
        rows = list_token_profiles()
        usable = [r for r in rows if not r.get("revoked") and not r.get("expired")]
        expiring = [r for r in usable if r.get("expiring_soon")]
        message = f"Token profiles: total={len(rows)} usable={len(usable)} expiring_soon={len(expiring)}"
        self.app.call_from_thread(self._set_profile_status, message)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed.id == "cloud":
            self._set_profile_controls_hidden(False)
            self.query_one("#auth-token", Input).focus()
            self._refresh_profiles_async()
        else:
            self._set_profile_controls_hidden(True)

    def _parse_profile_inputs(self) -> tuple[str, list[str], int | None]:
        profile_id = self.query_one("#auth-profile-id", Input).value.strip()
        scopes_raw = self.query_one("#auth-profile-scopes", Input).value.strip()
        expiry_raw = self.query_one("#auth-profile-expiry", Input).value.strip()
        scopes = [part.strip() for part in scopes_raw.split(",") if part.strip()]
        expiry_days = int(expiry_raw) if expiry_raw.isdigit() else None
        return profile_id, scopes, expiry_days

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ["btn-back", "btn-next"]:
            super().on_button_pressed(event)
            return

        if event.button.id == "btn-token-refresh":
            self._set_profile_status("Token profiles: refreshing...")
            self._refresh_profiles_async()
            return

        profile_id, scopes, expiry_days = self._parse_profile_inputs()
        token = self.query_one("#auth-token", Input).value.strip()

        if event.button.id == "btn-token-save":
            if not profile_id:
                self.notify(i18n.t("Token profile id is required."), severity="error")
                return
            if not token:
                self.notify(i18n.t("Token is required to save profile."), severity="error")
                return

            def _save_bg() -> None:
                profile = save_token_profile(
                    profile_id=profile_id,
                    token=token,
                    environment="cloud",
                    scopes=scopes,
                    expires_in_days=expiry_days,
                )
                profile_name = str(profile.get("profile_id") or profile_id)
                self.app.call_from_thread(self._set_profile_status, f"Saved profile: {profile_name}")
                self.app.call_from_thread(self._refresh_profiles_async)

            threading.Thread(target=_save_bg, daemon=True).start()
            return

        if event.button.id == "btn-token-use":
            if not profile_id:
                self.notify(i18n.t("Token profile id is required."), severity="error")
                return

            def _use_bg() -> None:
                result = use_token_profile(profile_id)
                used_token = str(result.get("token") or "")
                if used_token:
                    self.app.call_from_thread(self._set_auth_token_input, used_token)
                    self.app.call_from_thread(self._set_profile_status, f"Profile activated: {profile_id}")
                else:
                    self.app.call_from_thread(self._set_profile_status, f"Failed to activate profile: {profile_id}")
                self.app.call_from_thread(self._refresh_profiles_async)

            threading.Thread(target=_use_bg, daemon=True).start()
            return

        if event.button.id == "btn-token-revoke":
            if not profile_id:
                self.notify(i18n.t("Token profile id is required."), severity="error")
                return

            def _revoke_bg() -> None:
                profile = revoke_token_profile(profile_id)
                if profile.get("revoked"):
                    self.app.call_from_thread(self._set_profile_status, f"Profile revoked: {profile_id}")
                else:
                    self.app.call_from_thread(self._set_profile_status, f"Failed to revoke profile: {profile_id}")
                self.app.call_from_thread(self._refresh_profiles_async)

            threading.Thread(target=_revoke_bg, daemon=True).start()

    def on_next(self) -> None:
        mode = self.query_one("#auth-mode", RadioSet).pressed_button.id
        token = self.query_one("#auth-token", Input).value
        profile_id = self.query_one("#auth-profile-id", Input).value.strip()
        self.app.cfg["auth"] = {
            "mode": mode,
            "token_present": bool(token),
            "token_profile": profile_id,
        }
        self.safe_dismiss("search")

class SearchProviderScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Web Search / RAG Provider"), id="step-title")
            yield Label(i18n.t("Select search provider so your agent can fetch live information:"))
            
            with RadioSet(id="search-mode"):
                yield RadioButton(i18n.t("Brave Search (Structured results, filters)"), id="brave", value=True)
                yield RadioButton(i18n.t("Gemini (Google Search)"), id="gemini")
                yield RadioButton(i18n.t("Grok (xAI)"), id="grok")
                yield RadioButton(i18n.t("Kimi (Moonshot)"), id="kimi")
                yield RadioButton(i18n.t("Perplexity AI"), id="perplexity")
                yield RadioButton(i18n.t("Tavily (Built for AI agents)"), id="tavily")
                yield RadioButton(i18n.t("Skip for now"), id="none")
            yield Input(placeholder=i18n.t("API Key (Leave blank if you don't have one)..."), password=True, id="search-key")
            yield from self.compose_navigation()
        yield Footer()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        inp = self.query_one("#search-key", Input)
        if event.pressed.id == "none":
            inp.add_class("hidden")
        else:
            inp.remove_class("hidden")

    def on_next(self) -> None:
        mode = self.query_one("#search-mode", RadioSet).pressed_button.id
        key = self.query_one("#search-key", Input).value
        self.app.cfg["search"] = {"provider": mode, "has_key": bool(key)}
        self.safe_dismiss("providers")
