import json
import re
import socket
import time
import argparse
from pathlib import Path

from deep_translator import GoogleTranslator

ROOT_DIR = Path(__file__).resolve().parent
LOCALES_DIR = ROOT_DIR / "ironcore" / "tui" / "locales"
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

SCREEN_ROOT = ROOT_DIR / "ironcore" / "tui"
SUPPORTED_CODES = [
    "en", "vi", "zh", "ja", "fr", "de", "es", "it", "ko", "ru", "pt",
    "ar", "hi", "id", "th", "nl", "tr", "pl", "sv", "cs", "el", "ro",
    "hu", "uk", "bn", "he", "ta", "ur", "fa", "ms"
]
TRANSLATOR_CODE_MAP = {
    "zh": "zh-CN",
    "he": "iw",
}

socket.setdefaulttimeout(15)

EN_OVERRIDES = {
    "lang_title": "Choose Language",
    "lang_search_placeholder": "Search language...",
    "lang_no_results": "No language matched.",
    "btn_continue": "Continue",
    "btn_quit": "Quit",
}

KEY_PATTERN = re.compile(r'i18n\.t\("([^"]+)"')
MASK_PATTERN = re.compile(
    r"\[[^\]]+\]"
    r"|https?://[^\s)]+"
    r"|~?/\.ironcore/config\.json"
    r"|\b[A-Za-z_]+\.[A-Za-z0-9_]+\b"
)


def discover_i18n_keys() -> set[str]:
    discovered: set[str] = set()
    for file_path in SCREEN_ROOT.rglob("*.py"):
        content = file_path.read_text(encoding="utf-8")
        discovered.update(KEY_PATTERN.findall(content))
    return discovered


def load_locale(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def mask_text(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def repl(match: re.Match) -> str:
        token = match.group(0)
        idx = len(tokens)
        tokens.append(token)
        return f"__TOK_{idx}__"

    return MASK_PATTERN.sub(repl, text), tokens


def unmask_text(text: str, tokens: list[str]) -> str:
    restored = text
    for idx, token in enumerate(tokens):
        restored = restored.replace(f"__TOK_{idx}__", token)
    return restored


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def translate_many(translator: GoogleTranslator, sources: list[str], cache: dict[str, str]) -> None:
    pending = [source for source in sources if source not in cache and source.strip()]
    if not pending:
        return

    masked_map: dict[str, tuple[str, list[str]]] = {}
    for source in pending:
        masked_source, tokens = mask_text(source)
        masked_map[source] = (masked_source, tokens)

    masked_sources = [masked_map[source][0] for source in pending]
    masked_to_source = {masked_map[source][0]: source for source in pending}

    for batch in chunked(masked_sources, size=24):
        translated_batch: list[str] = []
        for _ in range(3):
            try:
                translated_batch = translator.translate_batch(batch)
                if translated_batch:
                    break
            except Exception:
                time.sleep(0.8)

        if translated_batch and len(translated_batch) == len(batch):
            for original_masked, translated_masked in zip(batch, translated_batch):
                source = masked_to_source[original_masked]
                _, tokens = masked_map[source]
                cache[source] = unmask_text(translated_masked, tokens)
            continue

        for original_masked in batch:
            source = masked_to_source[original_masked]
            _, tokens = masked_map[source]
            translated = original_masked
            for _ in range(3):
                try:
                    translated = translator.translate(original_masked)
                    break
                except Exception:
                    time.sleep(0.5)
            cache[source] = unmask_text(translated or source, tokens)

    for source in pending:
        if source not in cache:
            cache[source] = source


def build_en_locale(all_keys: list[str], current_en: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in all_keys:
        value = current_en.get(key, key)
        if key in EN_OVERRIDES and (value == key or not value.strip()):
            value = EN_OVERRIDES[key]
        result[key] = value
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync and translate TUI locale files")
    parser.add_argument(
        "--only",
        help="Comma-separated language codes to update (e.g. ko,fr,de).",
        default="",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    only_set = {code.strip() for code in args.only.split(",") if code.strip()}

    current_en = load_locale(LOCALES_DIR / "en.json")
    discovered_keys = discover_i18n_keys()
    all_keys = sorted(set(current_en.keys()) | discovered_keys | set(EN_OVERRIDES.keys()))

    en_locale = build_en_locale(all_keys, current_en)
    (LOCALES_DIR / "en.json").write_text(
        json.dumps(en_locale, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    print(f"[en] synced {len(en_locale)} keys")

    for code in SUPPORTED_CODES:
        if code == "en":
            continue
        if only_set and code not in only_set:
            continue

        target = TRANSLATOR_CODE_MAP.get(code, code)
        file_path = LOCALES_DIR / f"{code}.json"
        existing = load_locale(file_path)
        translator = GoogleTranslator(source="en", target=target)
        cache: dict[str, str] = {}

        needs_translation_keys = []
        for key in all_keys:
            source_text = en_locale[key]
            current_value = existing.get(key, "")
            if not current_value.strip() or current_value == key or current_value == source_text:
                needs_translation_keys.append(key)

        translate_many(
            translator,
            [en_locale[key] for key in needs_translation_keys],
            cache,
        )

        output: dict[str, str] = {}
        translated_count = 0
        for key in all_keys:
            source_text = en_locale[key]
            current_value = existing.get(key, "")

            if key in needs_translation_keys:
                value = cache.get(source_text, source_text)
                if value == source_text:
                    value = current_value or source_text
                else:
                    translated_count += 1
            else:
                value = current_value

            output[key] = value

        file_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        print(f"[{code}] translated/updated {translated_count} keys")
        time.sleep(0.2)

    print("Locale sync completed for all supported TUI languages.")


if __name__ == "__main__":
    main()
