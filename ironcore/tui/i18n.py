import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"

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

def supported_language_catalog() -> list[dict]:
    return [
        {"code": code, "name": name, "label": f"{name} ({code})"}
        for code, name in LANGUAGE_LABELS.items()
    ]

class I18nManager:
    def __init__(self):
        self.current_lang = "en"
        self.translations = {}
        self.load_language("en")

    def load_language(self, lang_code: str):
        self.current_lang = lang_code
        self.translations = {}
        
        # Base fallback
        en_path = LOCALES_DIR / "en.json"
        if en_path.exists():
            try:
                with open(en_path, "r", encoding="utf-8") as f:
                    self.translations.update(json.load(f))
            except Exception: pass

        if lang_code != "en":
            file_path = LOCALES_DIR / f"{lang_code}.json"
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations.update(json.load(f))
                except Exception: pass

    def t(self, key: str, default: str = "") -> str:
        return self.translations.get(key, default or key)

i18n = I18nManager()
