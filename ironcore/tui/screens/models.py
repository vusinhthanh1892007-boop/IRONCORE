from ironcore.tui.i18n import i18n
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, SelectionList, Input, RadioSet, RadioButton, ListView, ListItem
from textual.widgets.selection_list import Selection
from textual.containers import Vertical
from ironcore.tui.screens.base import BaseWizardScreen
from ironcore.tui.local_providers import scan_local_providers

import urllib.request
import json
import threading
import os
from textual.widgets import ListView, ListItem


LOCAL_PROVIDER_IDS = {"ollama", "localai", "vllm", "lmstudio"}
ENABLE_REMOTE_MODEL_FETCH = os.environ.get("IRONCORE_TUI_REMOTE_MODEL_FETCH", "0") == "1"

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
                Selection(i18n.t("LocalAI (Local)"), "localai"),
                Selection(i18n.t("vLLM (Local)"), "vllm"),
                Selection(i18n.t("LM Studio (Local)"), "lmstudio"),
                id="provider-list"
            )
            yield Label(i18n.t("Scanning local providers..."), id="local-provider-status")
            yield Label(i18n.t("Global Config:"))
            yield Input(placeholder=i18n.t("Multi-provider API Key (e.g. OpenRouter key)..."), password=True, id="provider-key")
            
            yield from self.compose_navigation()
        yield Footer()

    def on_mount(self) -> None:
        threading.Thread(target=self._scan_local_bg, daemon=True).start()

    def _scan_local_bg(self) -> None:
        scans = scan_local_providers()
        self.app.cfg["local_provider_scan"] = [
            {
                "id": scan.id,
                "label": scan.label,
                "base_url": scan.base_url,
                "available": scan.available,
                "models": [{"id": m.id, "name": m.name, "family": m.family} for m in scan.models],
                "error": scan.error,
            }
            for scan in scans
        ]
        try:
            self.app.call_from_thread(self._update_local_provider_status)
        except Exception:
            pass

    def _update_local_provider_status(self) -> None:
        status_label = self.query_one("#local-provider-status", Label)
        scan_rows = self.app.cfg.get("local_provider_scan", [])
        if not scan_rows:
            status_label.update(i18n.t("Local provider scan unavailable."))
            return

        parts = []
        for row in scan_rows:
            label = str(row.get("label") or row.get("id") or "unknown")
            available = bool(row.get("available"))
            count = len(row.get("models", []))
            if available:
                parts.append(f"{label}: online ({count} model{'s' if count != 1 else ''})")
            else:
                parts.append(f"{label}: offline")
        status_label.update(" | ".join(parts))

    def on_next(self) -> None:
        sel = list(self.query_one("#provider-list", SelectionList).selected)
        if not sel:
            self.notify(i18n.t("You must select at least one Provider!"), severity="error")
            return
        provider_key = self.query_one("#provider-key", Input).value
        self.app.cfg["providers"] = sel
        self.app.cfg["local_selected_providers"] = [provider for provider in sel if provider in LOCAL_PROVIDER_IDS]
        self.app.cfg["provider_key_present"] = bool(provider_key)
        self.safe_dismiss("model_picker")

class ModelPickerScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content-container"):
            yield Label(i18n.t("Primary Model Selection (Live from Web)"), id="step-title")
            yield Input(placeholder=i18n.t("Search 300+ models (e.g. claude, gpt, deepseek)..."), id="model-search")
            yield Input(placeholder=i18n.t("Or enter model manually (e.g. qwen2.5:7b)"), id="manual-model")
            yield Label(i18n.t("Loading models..."), id="loading-msg")
            
            # Using ListView for efficient display of lots of items
            yield ListView(id="model-list")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_mount(self) -> None:
        self.all_models = []
        self._item_mapping = {} # Store real model IDs mapping
        threading.Thread(target=self._fetch_models_bg, daemon=True).start()

    def _fetch_models_bg(self) -> None:
        models: list[dict] = []
        providers = self.app.cfg.get("providers", [])
        local_scans = self.app.cfg.get("local_provider_scan", [])
        selected_local = set(self.app.cfg.get("local_selected_providers", []))

        if selected_local and local_scans:
            for scan in local_scans:
                provider_id = scan.get("id")
                if provider_id not in selected_local:
                    continue
                if not scan.get("available"):
                    continue
                for model in scan.get("models", []):
                    model_id = str(model.get("id") or "").strip()
                    if not model_id:
                        continue
                    label = str(model.get("name") or model_id).strip()
                    models.append(
                        {
                            "id": model_id,
                            "name": f"{label} ({provider_id})",
                            "context_length": "N/A",
                        }
                    )
        
        if "ollama" in providers and not any(m.get("id") for m in models):
            try:
                # Fetch local tags safely from reconstructed Core module
                from ironcore.core.ollama_client import OllamaClient
                client = OllamaClient()
                if client.is_available():
                    for model_name in client.list_models():
                        models.append({"id": model_name, "name": model_name + " (Local)", "context_length": "N/A"})
            except Exception: pass

        if not models and ENABLE_REMOTE_MODEL_FETCH:
            try:
                req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "IronCore TUI"})
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode())
                    models = data.get("data", [])
            except Exception:
                models = []

        if not models:
            models = [
                {"id": "gpt-4o", "name": "GPT-4o"},
                {"id": "claude-4.6-sonnet", "name": "Claude 4.6 Sonnet"},
                {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"}
            ]
        
        self.all_models = models
        try:
            self.app.call_from_thread(self._update_list, "")
        except Exception: pass

    def _installed_local_model_ids(self) -> set[str]:
        scan_rows = self.app.cfg.get("local_provider_scan", [])
        selected_local = set(self.app.cfg.get("local_selected_providers", []))
        installed: set[str] = set()
        for row in scan_rows:
            if row.get("id") not in selected_local:
                continue
            if not row.get("available"):
                continue
            for model in row.get("models", []):
                model_id = str(model.get("id") or "").strip()
                if model_id:
                    installed.add(model_id)
        return installed

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
            self.safe_dismiss("channels")

    def on_next(self) -> None:
        manual_model = self.query_one("#manual-model", Input).value.strip()
        if manual_model:
            selected_local = set(self.app.cfg.get("local_selected_providers", []))
            if selected_local:
                installed = self._installed_local_model_ids()
                if installed and manual_model not in installed:
                    self.notify(i18n.t("Model is not installed on selected local provider(s)."), severity="error")
                    return
            self.app.cfg["primary_model"] = manual_model
            self.safe_dismiss("channels")
            return

        lst = self.query_one("#model-list", ListView)
        if lst.index is not None and lst.index >= 0 and lst.index < len(lst.children):
            item_id = lst.children[lst.index].id
            if item_id in self._item_mapping:
                self.app.cfg["primary_model"] = self._item_mapping[item_id]
                self.safe_dismiss("channels")
                return
        
        self.notify(i18n.t("You must select a primary model from the list!"), severity="error")
