import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"

class I18nManager:
    def __init__(self):
        self.current_lang = "en"
        self.translations = {}
        self.load_language("en")

    def load_language(self, lang_code: str):
        file_path = LOCALES_DIR / f"{lang_code}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
            self.current_lang = lang_code
        else:
            # Fallback to English if file doesn't exist
            if lang_code != "en":
                self.load_language("en")

    def t(self, key: str, default: str = "") -> str:
        return self.translations.get(key, default or key)

# Global instance
i18n = I18nManager()
