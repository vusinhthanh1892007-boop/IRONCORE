import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
LOCALES_PATH = WEB_SRC / "lib" / "static-locales.json"
CACHE_PATH = ROOT / "scripts" / ".translation_cache_web.json"
JOIN_SEPARATOR = " |||__ICSEP__||| "

LANG_OVERRIDES = {"he": "iw"}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def is_candidate_text(text: str) -> bool:
    if not text:
        return False
    text = normalize_space(text)
    if len(text) < 2 or len(text) > 180:
        return False
    if "${" in text:
        return False
    if text.startswith(("/", "./", "../", "@/", "http", "https", "data:", "#")):
        return False
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text):
        return False
    if sum(ch.isalpha() for ch in text) < 2:
        return False
    if re.search(r"[A-Za-zÀ-ỹ]", text) is None:
        return False

    blacklist = (
        "className",
        "use client",
        "use server",
        "application/json",
        "Content-Type",
        "Authorization",
        "Bearer ",
        "localhost",
        "function ",
        "interface ",
        "return ",
        "const ",
    )
    if any(token in text for token in blacklist):
        return False

    symbol_ratio = sum((not ch.isalnum()) and (not ch.isspace()) for ch in text) / max(len(text), 1)
    if symbol_ratio > 0.45:
        return False

    return True


def extract_candidates_from_file(path: Path) -> set[str]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    keys: set[str] = set()

    jsx_text_pattern = re.compile(r">([^<>{\\n][^<>{]{1,200}?)<")
    for raw in jsx_text_pattern.findall(content):
        text = normalize_space(raw)
        if is_candidate_text(text):
            keys.add(text)

    quote_pattern = re.compile(r"([\"'`])((?:\\\\.|(?!\\1).){1,220})\\1", re.S)
    for match in quote_pattern.finditer(content):
        raw = match.group(2)
        text = normalize_space(raw)
        if is_candidate_text(text):
            keys.add(text)

    return keys


def extract_all_candidates() -> set[str]:
    keys: set[str] = set()
    for path in WEB_SRC.rglob("*"):
        if path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        keys |= extract_candidates_from_file(path)
    return keys


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def translate_google_public(text: str, target: str) -> str:
    normalized_target = LANG_OVERRIDES.get(target, target)
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": normalized_target,
            "dt": "t",
            "q": text,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=6.5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        segments = payload[0] if isinstance(payload, list) and payload else []
        translated = "".join(part[0] for part in segments if isinstance(part, list) and part)
        translated = normalize_space(translated)
        if not translated:
            return text
        return translated
    except Exception:
        return text


def translate_batch_google_joined(texts: list[str], target: str) -> list[str]:
    if not texts:
        return []

    normalized_target = LANG_OVERRIDES.get(target, target)
    joined = JOIN_SEPARATOR.join(texts)
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": normalized_target,
            "dt": "t",
            "q": joined,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        segments = payload[0] if isinstance(payload, list) and payload else []
        translated = "".join(part[0] for part in segments if isinstance(part, list) and part)
        rows = [normalize_space(value) for value in translated.split(JOIN_SEPARATOR)]
        if len(rows) != len(texts):
            return texts
        return [row if row else src for row, src in zip(rows, texts)]
    except Exception:
        return texts


def save_progress(locales: dict, cache: dict) -> None:
    language_codes = list(locales.keys())
    ordered_locales: dict[str, dict[str, str]] = {}
    for code in language_codes:
        lang_dict = locales.get(code, {})
        if not isinstance(lang_dict, dict):
            lang_dict = {}
        ordered_locales[code] = {
            k: lang_dict.get(k, k if code == "en" else "") for k in sorted(locales["en"].keys())
        }

    LOCALES_PATH.write_text(json.dumps(ordered_locales, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    locales = load_json(LOCALES_PATH, {})
    if not locales or "en" not in locales:
        raise RuntimeError(f"Cannot load locales from {LOCALES_PATH}")

    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}

    candidate_keys = extract_all_candidates()

    for lang_dict in locales.values():
        if isinstance(lang_dict, dict):
            candidate_keys.update(lang_dict.keys())

    candidate_keys = {normalize_space(k) for k in candidate_keys if is_candidate_text(normalize_space(k))}

    locales["en"] = locales.get("en", {})
    for key in sorted(candidate_keys):
        locales["en"].setdefault(key, key)

    total_translated = 0
    total_skipped = 0

    language_codes = list(locales.keys())
    for code in language_codes:
        if code == "en":
            continue

        lang_dict = locales.get(code)
        if not isinstance(lang_dict, dict):
            lang_dict = {}
            locales[code] = lang_dict

        missing_keys = [
            key
            for key in sorted(locales["en"].keys())
            if not lang_dict.get(key) or normalize_space(lang_dict.get(key, "")) == key
        ]

        pending: list[str] = []
        for key in missing_keys:
            cache_key = f"{code}::{key}"
            if cache_key in cache and cache[cache_key]:
                lang_dict[key] = cache[cache_key]
                total_skipped += 1
                continue
            pending.append(key)

        chunk_size = 24
        for i in range(0, len(pending), chunk_size):
            chunk = pending[i : i + chunk_size]
            translated_rows = translate_batch_google_joined(chunk, code)
            if translated_rows == chunk:
                translated_rows = [translate_google_public(text, code) for text in chunk]

            for source_text, translated in zip(chunk, translated_rows):
                resolved = translated or source_text
                lang_dict[source_text] = resolved
                cache[f"{code}::{source_text}"] = resolved
                total_translated += 1

            time.sleep(0.04)

        print(f"[{code}] keys={len(lang_dict)} filled={len(missing_keys)}")
        save_progress(locales, cache)

    save_progress(locales, cache)
    print(f"Done. en_keys={len(locales['en'])}, translated={total_translated}, cache_hits={total_skipped}")


if __name__ == "__main__":
    main()
