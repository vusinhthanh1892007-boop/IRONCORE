from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, ListView, ListItem, Label
from textual.containers import Vertical
from ironcore.tui.i18n import i18n, supported_language_catalog
from ironcore.tui.lang_sync import push_language_to_backend

class LanguageItem(ListItem):
    def __init__(self, name: str, code: str, label: str):
        super().__init__()
        self.lang_name = name
        self.lang_code = code
        self.lang_label = label

    def compose(self) -> ComposeResult:
        yield Label(self.lang_label)

class LanguageScreen(Screen):
    BINDINGS = [
        ("escape", "app.quit", "Quit"),
        ("ctrl+q", "app.quit", "Quit")
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.languages = self._build_language_catalog()

    def _build_language_catalog(self) -> list[dict]:
        items = supported_language_catalog()
        items.sort(key=lambda x: x["name"].lower())
        return items

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="lang-container"):
            yield Label(i18n.t("lang_title"), id="lang-title")
            yield Input(placeholder=i18n.t("lang_search_placeholder"), id="lang-search")
            yield ListView(id="lang-list")
        yield Footer()

    def on_mount(self) -> None:
        self.title = i18n.t("lang_title")
        self.query_one("#lang-title").styles.text_align = "center"
        self.query_one("#lang-title").styles.padding = (1, 0)
        self.query_one("#lang-title").styles.text_style = "bold"
        self._populate_list(self.languages)
        self.query_one("#lang-search").focus()

    def _populate_list(self, items: list[dict]) -> None:
        list_view = self.query_one("#lang-list", ListView)
        list_view.clear()
        for item in items:
            list_view.append(LanguageItem(item["name"], item["code"], item["label"]))

    def on_input_changed(self, event: Input.Changed) -> None:
        needle = event.value.strip().lower()
        if not needle:
            self._populate_list(self.languages)
            return

        filtered = [
            item for item in self.languages
            if needle in item["name"].lower() or needle in item["code"] or needle in item["label"].lower()
        ]
        self._populate_list(filtered)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        selected_item = event.item
        if isinstance(selected_item, LanguageItem):
            # Change global language
            i18n.load_language(selected_item.lang_code)
            push_language_to_backend(selected_item.lang_code, source="tui-language-screen")
            # Save to config (assuming app handles config)
            if hasattr(self.app, "cfg"):
                self.app.cfg["language_code"] = selected_item.lang_code
                self.app.cfg["language"] = selected_item.lang_label
            
            # Dismiss screen to proceed with next screen
            self.dismiss(selected_item.lang_code)
