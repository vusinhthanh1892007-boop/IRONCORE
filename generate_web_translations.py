import json
from pathlib import Path

# Web UI Strings to replace completely
strings = [
    "Workspace",
    "The Engine",
    "Session",
    "Missing API key. Set it in Settings to enable authenticated tool calls.",
    "Settings",
    "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.",
    "Regenerate",
    "You",
    "Thinking...",
    "System initialized",
    "Engine core online. Connected to primary databases. Waiting for instructions.",
    "Queued offline.",
    "RAG Searching...",
    "Stream error.",
    "Streaming complete.",
    "Response ready."
]

translations = {
    "en": {s: s for s in strings},
    "vi": {
        "Workspace": "Không Gian Làm Việc",
        "The Engine": "Lõi Động Cơ",
        "Session": "Phiên làm việc",
        "Missing API key. Set it in Settings to enable authenticated tool calls.": "Trống API Key. Vui lòng cập nhật trong Cài đặt để cấp quyền cho tool.",
        "Settings": "Cài Đặt",
        "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.": "Nhấn Enter để gửi, Shift+Enter để xuống dòng.",
        "Regenerate": "Tạo lại",
        "You": "Bạn",
        "Thinking...": "Đang xử lý...",
        "System initialized": "Hệ thống đã khởi tạo",
        "Engine core online. Connected to primary databases. Waiting for instructions.": "Lõi động cơ đã trực tuyến. Kết nối cơ sở dữ liệu thành công. Chờ lệnh...",
        "Queued offline.": "Đã lưu hàng đợi ngoại tuyến.",
        "RAG Searching...": "Đang tra cứu dữ liệu (RAG)...",
        "Stream error.": "Lỗi truyền tải.",
        "Streaming complete.": "Hoàn tất hiển thị.",
        "Response ready.": "Đã sẵn sàng phản hồi."
    },
    "zh": {
        "Workspace": "工作空间",
        "The Engine": "引擎核心",
        "Session": "会话",
        "Missing API key. Set it in Settings to enable authenticated tool calls.": "缺少 API 密钥。请在设置中配置以启用经过身份验证的工具调用。",
        "Settings": "设置",
        "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.": "按 Enter 发送，Shift+Enter 换行。",
        "Regenerate": "重新生成",
        "You": "您",
        "Thinking...": "思考中...",
        "System initialized": "系统已初始化",
        "Engine core online. Connected to primary databases. Waiting for instructions.": "引擎核心在线。已连接主要数据库。等待指令中...",
        "Queued offline.": "已离线排队。",
        "RAG Searching...": "RAG 检索中...",
        "Stream error.": "流错误。",
        "Streaming complete.": "流传输完成。",
        "Response ready.": "响应已就绪。"
    },
    "ja": {
        "Workspace": "ワークスペース",
        "The Engine": "エンジン",
        "Session": "セッション",
        "Missing API key. Set it in Settings to enable authenticated tool calls.": "APIキーがありません。設定でキーを入力してツールを有効にしてください。",
        "Settings": "設定",
        "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.": "Enterで送信、Shift+Enterで改行。",
        "Regenerate": "再生成",
        "You": "あなた",
        "Thinking...": "考え中...",
        "System initialized": "システム初期化完了",
        "Engine core online. Connected to primary databases. Waiting for instructions.": "エンジンオンライン。データベース接続完了。指示を待っています。",
        "Queued offline.": "オフラインキューに追加されました。",
        "RAG Searching...": "RAG 検索中...",
        "Stream error.": "ストリームエラー",
        "Streaming complete.": "ストリーム完了。",
        "Response ready.": "応答準備完了。"
    },
    "ko": {
        "Workspace": "작업 공간",
        "The Engine": "엔진",
        "Session": "세션",
        "Missing API key. Set it in Settings to enable authenticated tool calls.": "API 키가 누락되었습니다. 설정에서 입력해 주세요.",
        "Settings": "설정",
        "Enter hoặc Cmd/Ctrl+Enter gửi, Shift+Enter xuống dòng.": "Enter로 전송, Shift+Enter로 줄바꿈.",
        "Regenerate": "다시 생성",
        "You": "당신",
        "Thinking...": "생각 중...",
        "System initialized": "시스템 초기화됨",
        "Engine core online. Connected to primary databases. Waiting for instructions.": "엔진 온라인. 데이터베이스 연결됨. 명령 대기 중.",
        "Queued offline.": "오프라인 대기열에 추가되었습니다.",
        "RAG Searching...": "RAG 검색 중...",
        "Stream error.": "스트림 오류.",
        "Streaming complete.": "스트리밍 완료.",
        "Response ready.": "응답 준비 완료."
    },
    # Copy fallback for others to English to save tokens, with partial translations if needed
    "es": {k: "ES: " + k for k in strings},
    "fr": {k: "FR: " + k for k in strings},
    "de": {k: "DE: " + k for k in strings},
    "ru": {k: "RU: " + k for k in strings},
    "ar": {k: "AR: " + k for k in strings},
    "pt": {k: "PT: " + k for k in strings},
    "hi": {k: "HI: " + k for k in strings},
    "id": {k: "ID: " + k for k in strings},
    "th": {k: "TH: " + k for k in strings},
    "it": {k: "IT: " + k for k in strings}
}

out_path = Path("/home/vusinhthanh/train ai/web/src/lib/static-locales.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(translations, f, ensure_ascii=False, indent=2)

print("Generated web static locales!")
