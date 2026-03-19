from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, SelectionList, Input, RadioSet, RadioButton
from textual.widgets.selection_list import Selection
from textual.containers import Vertical
from ironcore.tui.screens.base import BaseWizardScreen

class ModelProvidersScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Model Provider(s)", id="step-title")
            yield Label("Select the LLM providers you want to use:")
            
            yield SelectionList(
                Selection("OpenAI", "openai", True),
                Selection("Anthropic", "anthropic"),
                Selection("Google Gemini", "google"),
                Selection("Mistral", "mistral"),
                Selection("OpenRouter", "openrouter"),
                Selection("Ollama (Local)", "ollama"),
                id="provider-list"
            )
            yield Label("Global Config:")
            yield Input(placeholder="Multi-provider API Key (e.g. OpenRouter key)...", password=True, id="provider-key")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        sel = self.query_one("#provider-list", SelectionList).selected
        self.app.cfg["providers"] = sel
        self.dismiss("model_picker")

class ModelPickerScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label("Primary Model Selection", id="step-title")
            yield Label("Select the primary model for inference:")
            
            with RadioSet(id="model-list"):
                yield RadioButton("gpt-4o", id="gpt-4o", value=True)
                yield RadioButton("claude-3.5-sonnet", id="claude-3-5-sonnet")
                yield RadioButton("gemini-1.5-pro", id="gemini-1-5-pro")
                yield RadioButton("deepseek-r1", id="deepseek-r1")
                yield RadioButton("Mistral Large 2", id="mistral-large-2")
                yield RadioButton("local/phi-4", id="phi-4")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        model = self.query_one("#model-list", RadioSet).pressed_button.id
        self.app.cfg["primary_model"] = model
        self.dismiss("skills")
