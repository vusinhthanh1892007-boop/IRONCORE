from ironcore.tui.i18n import i18n
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, Input, RadioSet, RadioButton
from textual.containers import Vertical
from ironcore.tui.screens.base import BaseWizardScreen

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
            
            yield from self.compose_navigation()
        yield Footer()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        inp = self.query_one("#auth-token", Input)
        if event.pressed.id == "cloud":
            inp.remove_class("hidden")
            inp.focus()
        else:
            inp.add_class("hidden")

    def on_next(self) -> None:
        mode = self.query_one("#auth-mode", RadioSet).pressed_button.id
        token = self.query_one("#auth-token", Input).value
        self.app.cfg["auth"] = {"mode": mode, "token_present": bool(token)}
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
