import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"

class I18nManager:
    def __init__(self):
        self.current_lang = "en"
        self.translations = {}
        self.load_language("en")

    def load_language(self, lang_code: str):
        self.current_lang = lang_code
        self.translations = {}
        
        # Always load English base first (Fallback)
        en_path = LOCALES_DIR / "en.json"
        if en_path.exists():
            try:
                with open(en_path, "r", encoding="utf-8") as f:
                    self.translations.update(json.load(f))
            except Exception: pass

        # Overlay selected language
        file_path = LOCALES_DIR / f"{lang_code}.json"
        if file_path.exists() and lang_code != "en":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations.update(json.load(f))
            except Exception:
                pass

    def t(self, key: str, default: str = "") -> str:
        return self.translations.get(key, default or key)

# Global instance
i18n = I18nManager()
