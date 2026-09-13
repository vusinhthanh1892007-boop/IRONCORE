import json
import os
from pathlib import Path
from typing import Optional

LOCALES_DIR = Path(__file__).parent / "locales"
ENABLE_RUNTIME_TRANSLATION = os.environ.get("IRONCORE_TUI_RUNTIME_TRANSLATE", "1") == "1"

GOOGLE_LANGUAGE_MAP = {
    "zh": "zh-CN",
    "he": "iw",
}

EN_DEFAULT_KEYS = {
    "lang_title": "Choose Language",
    "lang_search_placeholder": "Search language...",
    "lang_no_results": "No language matched.",
    "btn_continue": "Continue",
    "btn_quit": "Quit",
}

LANGUAGE_LABELS = {
    "en": "English", "vi": "Vietnamese", "zh": "Chinese", "ja": "Japanese",
    "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
    "ko": "Korean", "ru": "Russian", "pt": "Portuguese", "ar": "Arabic",
    "hi": "Hindi", "id": "Indonesian", "th": "Thai", "nl": "Dutch",
    "tr": "Turkish", "pl": "Polish", "sv": "Swedish", "cs": "Czech",
    "el": "Greek", "ro": "Romanian", "hu": "Hungarian", "uk": "Ukrainian",
    "bn": "Bengali", "he": "Hebrew", "ta": "Tamil", "ur": "Urdu",
    "fa": "Persian", "ms": "Malay"
}


def normalize_language(code: str) -> str:
    value = (code or "").strip().lower().replace("_", "-")
    if not value:
        return "en"
    return value.split("-")[0]

def supported_language_catalog() -> list[dict]:
    return [
        {"code": code, "name": name, "label": f"{name} ({code})"}
        for code, name in LANGUAGE_LABELS.items()
    ]

class I18nManager:
    def __init__(self):
        self.current_lang = "en"
        self.base_translations = {}
        self.translations = {}
        self._runtime_cache = {}
        self._translator = None
        self.load_language("en")

    def load_language(self, lang_code: str):
        lang_code = normalize_language(lang_code)
        self.current_lang = lang_code
        self._translator = None
        self._runtime_cache = {}
        self.translations = {}
        self.base_translations = {}
        
        # Base fallback
        en_path = LOCALES_DIR / "en.json"
        if en_path.exists():
            try:
                with open(en_path, "r", encoding="utf-8") as f:
                    self.base_translations = json.load(f)
            except Exception: pass

        self.translations.update(self.base_translations)

        if lang_code != "en":
            file_path = LOCALES_DIR / f"{lang_code}.json"
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations.update(json.load(f))
                except Exception: pass

    def _source_text(self, key: str, default: str = "") -> str:
        if key in EN_DEFAULT_KEYS:
            value = self.base_translations.get(key, "")
            if value and value != key:
                return value
            return EN_DEFAULT_KEYS[key]
        return self.base_translations.get(key, default or key)

    def _target_language_code(self) -> str:
        return GOOGLE_LANGUAGE_MAP.get(self.current_lang, self.current_lang)

    def _translate_with_provider(self, text: str) -> Optional[str]:
        if not ENABLE_RUNTIME_TRANSLATION:
            return None

        if self.current_lang == "en" or not text.strip():
            return text

        if text in self._runtime_cache:
            return self._runtime_cache[text]

        try:
            if self._translator is None:
                from deep_translator import GoogleTranslator

                self._translator = GoogleTranslator(source="en", target=self._target_language_code())

            translated = self._translator.translate(text)
            if translated:
                self._runtime_cache[text] = translated
                return translated
        except Exception:
            return None

        return None

    def _persist_runtime_translation(self, key: str, value: str) -> None:
        if self.current_lang == "en":
            return

        file_path = LOCALES_DIR / f"{self.current_lang}.json"
        try:
            payload = {}
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            payload[key] = value
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def t(self, key: str, default: str = "") -> str:
        source_text = self._source_text(key, default)
        current = self.translations.get(key, "")

        if not current:
            current = default or source_text

        needs_runtime_translation = (
            self.current_lang != "en"
            and (current == key or current == source_text or current in EN_DEFAULT_KEYS.values())
        )

        if needs_runtime_translation:
            generated = self._translate_with_provider(source_text)
            if generated and generated != source_text:
                self.translations[key] = generated
                self._persist_runtime_translation(key, generated)
                return generated

        return current or source_text

i18n = I18nManager()
