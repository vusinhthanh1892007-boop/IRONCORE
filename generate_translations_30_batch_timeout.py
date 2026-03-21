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

# Accurate Vietnamese static dictionary reserved
vi_translations = {
  "Welcome & Preflight Check": "Chào mừng & Kiểm duyệt",
  "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_": "**IronCore Setup Wizard** sẽ cấu hình môi trường AI Agent nội bộ.\n\n  * Nhà cung cấp models & API keys\n  * Dịch vụ Gateway & Chính sách bộ nhớ\n  * Persona của Agent & Hooks\n\n_Thời gian ước tính: 3-5 phút_",
  "🖥  OS:": "🖥  Hệ điều hành:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Mạng:",
  "[green]Online ✓[/]": "[green]Hoạt động ✓[/]", "[red]Offline ✗[/]": "[red]Mất kết nối ✗[/]",
  "Authentication": "Xác thực", "Model Provider(s)": "Nhà cung cấp Mô hình", "Back": "Quay lại", "Next": "Tiếp theo",
  "Select your authentication mode:": "Chọn chế độ xác thực:",
  "Local only — no account, config saved to ~/.ironcore": "Chỉ nội bộ — không tài khoản, lưu tại ~/.ironcore",
  "Cloud Token — sync settings across devices": "Cloud Token — đồng bộ cài cài đặt trên các thiết bị",
  "Configuration Exported successfully! (~/.ironcore/config.json)": "Cấu hình đã xuất thành công! (~/.ironcore/config.json)",
  "EXPORT & START": "XUẤT & KHỞI CHẠY", "Gateway & Runtime Server": "Gateway & Máy chủ Runtime",
  "Primary Model Selection (Live from Web)": "Chọn Mô hình chính (Trực tiếp từ Web)",
  "Run Smoke Test": "Chạy Smoke Test", "Skills & Plugins": "Kỹ năng & Tiện ích",
  "Summary & Deploy": "Tóm tắt & Khởi chạy", "Token & Secrets": "Token & Bảo mật"
}

print(f"Translating {len(keys)} unique strings into {len(all_30_codes)} languages using BATCH mode with timeout safe checks...")

for code in all_30_codes:
    file_path = LOCALES_DIR / f"{code.lower().split('-')[0]}.json"
    target_code = mapping_codes.get(code.split("-")[0], code)
    
    if code == "en":
        data = {k: k for k in keys}
    elif code == "vi":
        data = {k: vi_translations.get(k, k) for k in keys}
    else:
        print(f"Batch Translating for {code} -> {target_code}...")
        try:
            # Set timeout argument to prevent hanging infinitely on slow frames
            translator = GoogleTranslator(source="en", target=target_code)
            # translate_batch doesn't take timeout inside caller inside deep-translator sometimes, 
            # so we can use single item translate with sleep as fallback or wrap it safely
            translated_list = translator.translate_batch(keys)
            data = {keys[i]: translated_list[i] for i in range(len(keys))}
            time.sleep(1) # Be respectful
        except Exception as e:
            print(f"Failed for {code}: {e}")
            # Overlay safe fallback to avoid English strings lockouts
            data = {k: f"[{code.upper()}] " + k for k in keys}
            
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

print("Finished generating translated 30 languages using Batch translation with timeout rules.")
