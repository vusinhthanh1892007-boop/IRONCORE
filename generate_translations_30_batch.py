import json
import time
from pathlib import Path
from deep_translator import GoogleTranslator

LOCALES_DIR = Path("/home/vusinhthanh/train ai/ironcore/tui/locales")
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

with open("/tmp/unique_keys.json", "r") as f:
    keys = json.load(f)

all_30_codes = [
    "en", "vi", "zh-CN", "ja", "fr", "de", "es", "it", "ko", "ru", "pt", "ar", "hi", "id", "th", "nl", "tr", "pl", "sv", "cs", "el", "ro", "hu", "uk", "bn", "he", "ta", "ur", "fa", "ms"
]

mapping_codes = {
    "zh": "zh-CN", "he": "iw"
}

# Accurate Vietnamese mapping correctly preserved
vi_translations = {
  "Welcome & Preflight Check": "Chào mừng & Kiểm duyệt",
  "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_": "**IronCore Setup Wizard** sẽ cấu hình môi trường AI Agent nội bộ.\n\n  * Nhà cung cấp models & API keys\n  * Dịch vụ Gateway & Chính sách bộ nhớ\n  * Persona của Agent & Hooks\n\n_Thời gian ước tính: 3-5 phút_",
  "🖥  OS:": "🖥  Hệ điều hành:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Mạng:",
  "[green]Online ✓[/]": "[green]Hoạt động ✓[/]", "[red]Offline ✗[/]": "[red]Mất kết nối ✗[/]",
  "Authentication": "Xác thực", "Model Provider(s)": "Nhà cung cấp Mô hình", "Back": "Quay lại", "Next": "Tiếp theo"
}

print(f"Translating {len(keys)} unique strings into {len(all_30_codes)} languages using BATCH mode...")

for code in all_30_codes:
    file_path = LOCALES_DIR / f"{code.lower().split('-')[0]}.json"
    target_code = mapping_codes.get(code.split("-")[0], code)
    
    if code == "en":
        data = {k: k for k in keys}
    elif code == "vi":
        # Safe full Vi manual map overlay
        data = {k: vi_translations.get(k, k) for k in keys}
    else:
        print(f"Batch Translating for {code} -> {target_code}...")
        try:
            translator = GoogleTranslator(source="en", target=target_code)
            translated_list = translator.translate_batch(keys)
            data = {keys[i]: translated_list[i] for i in range(len(keys))}
            time.sleep(1) # Be respectful to and rate limits
        except Exception as e:
            print(f"Failed for {code}: {e}")
            data = {k: f"[{code.upper()}] " + k for k in keys}
            
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

print("Finished generating translated 30 languages using Batch translation.")
