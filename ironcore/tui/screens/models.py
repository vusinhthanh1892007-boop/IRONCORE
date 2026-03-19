from ironcore.tui.i18n import i18n
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, SelectionList, Input, RadioSet, RadioButton, ListView, ListItem
from textual.widgets.selection_list import Selection
from textual.containers import Vertical
from ironcore.tui.screens.base import BaseWizardScreen

class ModelProvidersScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Model Provider(s)"), id="step-title")
            yield Label(i18n.t("Select the LLM providers you want to use:"))
            
            yield SelectionList(
                Selection(i18n.t("OpenAI"), "openai", True),
                Selection(i18n.t("Anthropic"), "anthropic"),
                Selection(i18n.t("Google"), "google"),
                Selection(i18n.t("Meta"), "meta"),
                Selection(i18n.t("Mistral"), "mistral"),
                Selection(i18n.t("DeepSeek"), "deepseek"),
                Selection(i18n.t("Cohere"), "cohere"),
                Selection(i18n.t("Alibaba (Qwen)"), "alibaba"),
                Selection(i18n.t("Zhipu (ChatGLM)"), "zhipu"),
                Selection(i18n.t("Moonshot (Kimi)"), "moonshot"),
                Selection(i18n.t("Tencent"), "tencent"),
                Selection(i18n.t("ByteDance"), "bytedance"),
                Selection(i18n.t("Stability AI"), "stability"),
                Selection(i18n.t("Runway"), "runway"),
                Selection(i18n.t("Black Forest Labs"), "blackforest"),
                Selection(i18n.t("OpenRouter"), "openrouter"),
                Selection(i18n.t("Together AI"), "together"),
                Selection(i18n.t("Replicate"), "replicate"),
                Selection(i18n.t("Fireworks AI"), "fireworks"),
                Selection(i18n.t("HuggingFace"), "huggingface"),
                Selection(i18n.t("Azure AI Foundry"), "azure"),
                Selection(i18n.t("AWS Bedrock"), "aws"),
                Selection(i18n.t("NVIDIA NIM"), "nvidia"),
                Selection(i18n.t("xAI (Grok)"), "xai"),
                Selection(i18n.t("RunPod"), "runpod"),
                Selection(i18n.t("Modal"), "modal"),
                Selection(i18n.t("Ollama (Local)"), "ollama"),
                Selection(i18n.t("vLLM (Local)"), "vllm"),
                id="provider-list"
            )
            yield Label(i18n.t("Global Config:"))
            yield Input(placeholder=i18n.t("Multi-provider API Key (e.g. OpenRouter key)..."), password=True, id="provider-key")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        sel = self.query_one("#provider-list", SelectionList).selected
        if not sel:
            self.notify(i18n.t("You must select at least one Provider!"), severity="error")
            return
        self.app.cfg["providers"] = sel
        self.dismiss("model_picker")

import urllib.request
import json
import threading
from textual.widgets import ListView, ListItem

class ModelPickerScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Primary Model Selection (Live from Web)"), id="step-title")
            yield Input(placeholder=i18n.t("Search 300+ models (e.g. claude, gpt, deepseek)..."), id="model-search")
            yield Label(i18n.t("Loading models from internet in real-time... Please wait."), id="loading-msg")
            
            # Using ListView for efficient display of lots of items
            yield ListView(id="model-list")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_mount(self) -> None:
        self.all_models = []
        self._item_mapping = {} # Store real model IDs mapping
        threading.Thread(target=self._fetch_models_bg, daemon=True).start()

    def _fetch_models_bg(self) -> None:
        models = []
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "IronCore TUI"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                models = data.get("data", [])
        except Exception:
            models = [
                {"id": "gpt-4o", "name": "GPT-4o"},
                {"id": "claude-4.6-sonnet", "name": "Claude 4.6 Sonnet"},
                {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"}
            ]
        
        self.all_models = models
        try:
            self.app.call_from_thread(self._update_list, "")
        except Exception:
            pass # Ignore if app context is dead

    def _update_list(self, filter_text: str) -> None:
        try:
            lbl = self.query_one("#loading-msg", Label)
            lbl.display = False
        except Exception:
            pass

        lst = self.query_one("#model-list", ListView)
        lst.clear()
        self._item_mapping.clear()
        
        count = 0
        filter_lower = filter_text.lower()
        for idx, m in enumerate(self.all_models):
            mid = m.get("id", "")
            mname = m.get("name", "")
            if filter_lower in mid.lower() or filter_lower in mname.lower():
                item_id = f"model_item_{idx}"
                self._item_mapping[item_id] = mid
                ctx = m.get("context_length", "N/A")
                lst.append(ListItem(Label(f"[{mid}] {mname} (Ctx: {ctx})"), id=item_id))
                count += 1
                if count >= 100: # Limit to 100 for TUI performance
                    break
                    
        if count == 0:
            lst.append(ListItem(Label(i18n.t("No models found matching your search.")), id="none"))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "model-search":
            self._update_list(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id
        if item_id in self._item_mapping:
            self.app.cfg["primary_model"] = self._item_mapping[item_id]
            self.dismiss("channels")

    def on_next(self) -> None:
        lst = self.query_one("#model-list", ListView)
        if lst.index is not None and lst.index >= 0 and lst.index < len(lst.children):
            item_id = lst.children[lst.index].id
            if item_id in self._item_mapping:
                self.app.cfg["primary_model"] = self._item_mapping[item_id]
                self.dismiss("channels")
                return
        
        self.notify(i18n.t("You must select a primary model from the list!"), severity="error")
