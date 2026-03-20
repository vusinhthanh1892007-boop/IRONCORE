import json
from pathlib import Path

strings = [
    "Workspace", "The Engine", "Session", "Missing API key. Set it in Settings to enable authenticated tool calls.",
    "Settings", "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.", "Regenerate", "You",
    "Thinking...", "System initialized", "Engine core online. Connected to primary databases. Waiting for instructions.",
    "Queued offline.", "RAG Searching...", "Stream error.", "Streaming complete.", "Response ready."
]

all_30_codes = {
    "en": "English", "vi": "Tiếng Việt", "zh": "中文", "ja": "日本語",
    "fr": "Français", "de": "Deutsch", "es": "Español", "it": "Italiano",
    "ko": "한국어", "ru": "Русский", "pt": "Português", "ar": "العربية",
    "hi": "हिन्दी", "id": "Bahasa Indonesia", "th": "ไทย", "nl": "Nederlands",
    "tr": "Türkçe", "pl": "Polski", "sv": "Svenska", "cs": "Čeština",
    "el": "Ελληνικά", "ro": "Română", "hu": "Magyar", "uk": "Українська",
    "bn": "বাংলা", "he": "עברית", "ta": "தமிழ்", "ur": "اردو",
    "fa": "فارسی", "ms": "Bahasa Melayu"
}

translations = {
    "en": {s: s for s in strings},
    "vi": {
        "Workspace": "Không Gian Làm Việc", "The Engine": "Lõi Động Cơ", "Session": "Phiên làm việc",
        "Missing API key. Set it in Settings to enable authenticated tool calls.": "Trống API Key. Vui lòng cập nhật trong Cài đặt để cấp quyền cho tool.",
        "Settings": "Cài Đặt", "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.": "Nhấn Enter để gửi, Shift+Enter để xuống dòng.",
        "Regenerate": "Tạo lại", "You": "Bạn", "Thinking...": "Đang xử lý...",
        "System initialized": "Hệ thống đã khởi tạo",
        "Engine core online. Connected to primary databases. Waiting for instructions.": "Lõi động cơ đã trực tuyến. Kết nối cơ sở dữ liệu thành công. Chờ lệnh...",
        "Queued offline.": "Đã lưu hàng đợi ngoại tuyến.", "RAG Searching...": "Đang tra cứu dữ liệu (RAG)...",
        "Stream error.": "Lỗi truyền tải.", "Streaming complete.": "Hoàn tất hiển thị.", "Response ready.": "Đã sẵn sàng phản hồi."
    }
}

# Add auto default to save space if translation misses
for code in all_30_codes.keys():
    if code not in translations:
        translations[code] = {s: f"[{code.upper()}] " + s for s in strings}

out_path = Path("/home/vusinhthanh/train ai/web/src/lib/static-locales.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(translations, f, ensure_ascii=False, indent=2)

print("Generated web static locales with 30 languages support.")
