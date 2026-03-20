import json
import os
from pathlib import Path

LOCALES_DIR = Path("/home/vusinhthanh/train ai/ironcore/tui/locales")
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

# Define English base explicitly to serve as the template
base_translations = {
    "en": {
        "lang_title": "Choose Language",
        "lang_search_placeholder": "Search language by name or code...",
        "lang_no_results": "No language matched. Try another keyword.",
        "btn_continue": "Continue",
        "btn_quit": "Quit",
        "preflight_title": "Welcome & Preflight Check",
        "preflight_body": "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_",
        "preflight_os_label": "OS",
        "preflight_python_label": "Python",
        "preflight_network_label": "Network",
        "preflight_network_online": "[green]Online ✓[/]",
        "preflight_network_offline": "[red]Offline ✗[/]"
    },
    "vi": {
        "lang_title": "Chọn Ngôn Ngữ",
        "lang_search_placeholder": "Tìm kiếm theo tên hoặc mã...",
        "lang_no_results": "Không tìm thấy ngôn ngữ nào. Thử từ khóa khác.",
        "btn_continue": "Tiếp tục",
        "btn_quit": "Thoát",
        "preflight_title": "Chào mừng & Kiểm duyệt hệ thống",
        "preflight_body": "**Chương trình Thiết lập IronCore** sẽ cấu hình môi trường AI Agent nội bộ.\n\n  * Nhà cung cấp mô hình & API keys\n  * Dịch vụ Gateway & Bộ nhớ\n  * Tính cách & Webhooks\n\n_Ước tính thời gian: 3-5 phút_",
        "preflight_os_label": "Hệ điều hành",
        "preflight_python_label": "Môi trường Python",
        "preflight_network_label": "Kết nối mạng",
        "preflight_network_online": "[green]Hoạt động ✓[/]",
        "preflight_network_offline": "[red]Mất kết nối ✗[/]"
    },
    "zh": {
        "lang_title": "选择语言",
        "lang_search_placeholder": "按名称或代码搜索语言...",
        "lang_no_results": "未找到匹配的语言。请尝试其他关键字。",
        "btn_continue": "继续",
        "btn_quit": "退出",
        "preflight_title": "欢迎与系统环境检查",
        "preflight_body": "**IronCore 安装向导**将配置您的本地 AI 代理运行环境。\n\n  * 模型提供商与 API 密钥\n  * 网关服务与记忆策略\n  * 代理属性与 Webhooks\n\n_预计时间：3-5 分钟_",
        "preflight_os_label": "操作系统",
        "preflight_python_label": "Python 环境",
        "preflight_network_label": "网络状态",
        "preflight_network_online": "[green]在线 ✓[/]",
        "preflight_network_offline": "[red]离线 ✗[/]"
    },
    "ja": {
        "lang_title": "言語を選択",
        "lang_search_placeholder": "名前またはコードで検索...",
        "lang_no_results": "一致する言語がありません。",
        "btn_continue": "次へ",
        "btn_quit": "終了",
        "preflight_title": "ようこそ & システム要件チェック",
        "preflight_body": "**IronCore セットアップ** はローカルAIエージェントを構成します。\n\n  * モデルプロバイダ & APIキー\n  * ゲートウェイサービス & メモリ\n  * エージェントの属性 & フック\n\n_所要時間: 3〜5分_",
        "preflight_os_label": "OS",
        "preflight_python_label": "Python環境",
        "preflight_network_label": "ネットワーク",
        "preflight_network_online": "[green]オンライン ✓[/]",
        "preflight_network_offline": "[red]オフライン ✗[/]"
    },
    "ko": {
        "lang_title": "언어 선택",
        "lang_search_placeholder": "이름이나 코드로 검색...",
        "lang_no_results": "일치하는 언어가 없습니다.",
        "btn_continue": "계속",
        "btn_quit": "종료",
        "preflight_title": "환영합니다 & 시스템 점검",
        "preflight_body": "**IronCore 설정 마법사**는 로컬 AI 에이전트 환경을 구성합니다.\n\n  * 모델 제공업체 및 API 키\n  * 게이트웨이 서비스 및 메모리\n  * 에이전트 페르소나 및 훅\n\n_예상 시간: 3-5분_",
        "preflight_os_label": "운영 체제",
        "preflight_python_label": "파이썬 환경",
        "preflight_network_label": "네트워크",
        "preflight_network_online": "[green]온라인 ✓[/]",
        "preflight_network_offline": "[red]오프라인 ✗[/]"
    },
    "es": {
        "lang_title": "Elegir Idioma",
        "lang_search_placeholder": "Buscar por nombre o código...",
        "lang_no_results": "No hay resultados. Intente con otra palabra.",
        "btn_continue": "Continuar",
        "btn_quit": "Salir",
        "preflight_title": "Bienvenido y Comprobación del Sistema",
        "preflight_body": "El **Asistente de IronCore** configurará su agente de IA local.\n\n  * Proveedores de modelos y APIs\n  * Puerta de enlace y Memoria\n  * Personalidad y Webhooks\n\n_Tiempo estimado: 3-5 min_",
        "preflight_os_label": "Sistema Operativo",
        "preflight_python_label": "Python",
        "preflight_network_label": "Red",
        "preflight_network_online": "[green]En línea ✓[/]",
        "preflight_network_offline": "[red]Desconectado ✗[/]"
    },
    "fr": {
        "lang_title": "Choisir la Langue",
        "lang_search_placeholder": "Rechercher par nom ou code...",
        "lang_no_results": "Aucune langue trouvée.",
        "btn_continue": "Continuer",
        "btn_quit": "Quitter",
        "preflight_title": "Bienvenue et Vérification du Système",
        "preflight_body": "L'**Assistant IronCore** va configurer votre agent IA.\n\n  * Fournisseurs & clés API\n  * Passerelle & Mémoire\n  * Persona & Webhooks\n\n_Durée estimée : 3 à 5 minutes_",
        "preflight_os_label": "Système",
        "preflight_python_label": "Python",
        "preflight_network_label": "Réseau",
        "preflight_network_online": "[green]Connecté ✓[/]",
        "preflight_network_offline": "[red]Hors ligne ✗[/]"
    },
    "de": {
        "lang_title": "Sprache Auswählen",
        "lang_search_placeholder": "Suchen Sie nach Namen oder Code...",
        "lang_no_results": "Keine Sprache gefunden.",
        "btn_continue": "Weiter",
        "btn_quit": "Beenden",
        "preflight_title": "Willkommen & Systemprüfung",
        "preflight_body": "Der **IronCore Setup-Assistent** konfiguriert Ihren lokalen KI-Agenten.\n\n  * Modelle & API-Schlüssel\n  * Gateway-Dienst & Speicher\n  * Agenten-Persona & Hooks\n\n_Geschätzte Zeit: 3-5 Minuten_",
        "preflight_os_label": "Betriebssystem",
        "preflight_python_label": "Python",
        "preflight_network_label": "Netzwerk",
        "preflight_network_online": "[green]Online ✓[/]",
        "preflight_network_offline": "[red]Offline ✗[/]"
    },
    "ru": {
        "lang_title": "Выберите Язык",
        "lang_search_placeholder": "Поиск по названию или коду...",
        "lang_no_results": "Язык не найден. Попробуйте еще раз.",
        "btn_continue": "Продолжить",
        "btn_quit": "Выход",
        "preflight_title": "Добро пожаловать и проверка системы",
        "preflight_body": "**Мастер установки IronCore** настроит вашу среду ИИ.\n\n  * Модели и ключи API\n  * Шлюз и память\n  * Личность и вебхуки\n\n_Ожидаемое время: 3-5 минут_",
        "preflight_os_label": "ОС",
        "preflight_python_label": "Python",
        "preflight_network_label": "Сеть",
        "preflight_network_online": "[green]В сети ✓[/]",
        "preflight_network_offline": "[red]Не в сети ✗[/]"
    },
    "ar": {
        "lang_title": "اختر اللغة",
        "lang_search_placeholder": "ابحث بالاسم أو الرمز...",
        "lang_no_results": "لم يتم العثور على اللغة.",
        "btn_continue": "استمرار",
        "btn_quit": "خروج",
        "preflight_title": "مرحباً و فحص النظام",
        "preflight_body": "**معالج إعداد IronCore** سيهيئ بيئة الذكاء الاصطناعي.\n\n  * النماذج ومفاتيح API\n  * بوابة العبور والذاكرة\n  * السمات الشخصية\n\n_الوقت المقدر: ٣-٥ دقائق_",
        "preflight_os_label": "نظام التشغيل",
        "preflight_python_label": "بايثون",
        "preflight_network_label": "الشبكة",
        "preflight_network_online": "[green]متصل ✓[/]",
        "preflight_network_offline": "[red]غير متصل ✗[/]"
    },
    "pt": {
        "lang_title": "Escolher Idioma",
        "lang_search_placeholder": "Buscar por nome ou código...",
        "lang_no_results": "Nenhum idioma encontrado.",
        "btn_continue": "Continuar",
        "btn_quit": "Sair",
        "preflight_title": "Bem-vindo e Verificação do Sistema",
        "preflight_body": "O **Assistente IronCore** configurará sua IA local.\n\n  * Modelos e APIs\n  * Gateway e Espaço de Memória\n  * Persona do Agente\n\n_Tempo estimado: 3-5 min_",
        "preflight_os_label": "Sistema",
        "preflight_python_label": "Python",
        "preflight_network_label": "Rede",
        "preflight_network_online": "[green]Online ✓[/]",
        "preflight_network_offline": "[red]Offline ✗[/]"
    },
    "hi": {
        "lang_title": "भाषा चुनें",
        "lang_search_placeholder": "नाम या कोड से खोजें...",
        "lang_no_results": "कोई भाषा नहीं मिली।",
        "btn_continue": "जारी रखें",
        "btn_quit": "छोड़ें",
        "preflight_title": "स्वागत और सिस्टम जाँच",
        "preflight_body": "**IronCore विज़ार्ड** आपके AI सिस्टम को सेट करेगा।\n\n  * मॉडल और API\n  * गेटवे और मेमोरी\n  * एजेंट व्यक्तिगतता\n\n_अनुमानित समय: 3-5 मिनट_",
        "preflight_os_label": "ऑपरेटिंग सिस्टम",
        "preflight_python_label": "पायथन",
        "preflight_network_label": "नेटवर्क",
        "preflight_network_online": "[green]ऑनलाइन ✓[/]",
        "preflight_network_offline": "[red]ऑफ़लाइन ✗[/]"
    },
    "id": {
        "lang_title": "Pilih Bahasa",
        "lang_search_placeholder": "Cari berdasarkan nama atau kode...",
        "lang_no_results": "Bahasa tidak ditemukan.",
        "btn_continue": "Lanjutkan",
        "btn_quit": "Keluar",
        "preflight_title": "Selamat Datang & Cek Sistem",
        "preflight_body": "**IronCore Wizard** akan mengatur AI Agent Anda.\n\n  * Model & Kunci API\n  * Layanan Gateway & Memori\n  * Persona & Hooks\n\n_Waktu: 3-5 menit_",
        "preflight_os_label": "OS",
        "preflight_python_label": "Python",
        "preflight_network_label": "Jaringan",
        "preflight_network_online": "[green]Online ✓[/]",
        "preflight_network_offline": "[red]Offline ✗[/]"
    },
    "th": {
        "lang_title": "เลือกภาษา",
        "lang_search_placeholder": "ค้นหาด้วยชื่อหรือรหัส...",
        "lang_no_results": "ไม่พบภาษาที่ค้นหา",
        "btn_continue": "ดำเนินการต่อ",
        "btn_quit": "ออก",
        "preflight_title": "ยินดีต้อนรับ & ตรวจสอบระบบ",
        "preflight_body": "**IronCore Wizard** จะกำหนดค่า AI Agent ของคุณ\n\n  * ตั้งค่า API และโมเดล\n  * บริการเครือข่าย\n  * ข้อมูลส่วนตัวตัวแทน\n\n_เวลาโดยประมาณ: 3-5 นาที_",
        "preflight_os_label": "ระบบปฏิบัติการ",
        "preflight_python_label": "ไพธอน",
        "preflight_network_label": "เครือข่าย",
        "preflight_network_online": "[green]ออนไลน์ ✓[/]",
        "preflight_network_offline": "[red]ออฟไลน์ ✗[/]"
    },
    "it": {
        "lang_title": "Scegli Lingua",
        "lang_search_placeholder": "Cerca per nome o codice...",
        "lang_no_results": "Nessuna lingua trovata.",
        "btn_continue": "Continua",
        "btn_quit": "Esci",
        "preflight_title": "Benvenuto e Controllo Sistema",
        "preflight_body": "La configurazione di **IronCore** imposterà il tuo AI agent.\n\n  * Modelli & API Keys\n  * Gateway & Memoria\n  * Persona & Webhooks\n\n_Tempo stimato: 3-5 minuti_",
        "preflight_os_label": "Sistema Operativo",
        "preflight_python_label": "Python",
        "preflight_network_label": "Rete",
        "preflight_network_online": "[green]Online ✓[/]",
        "preflight_network_offline": "[red]Offline ✗[/]"
    }
}

for lang_code, data in base_translations.items():
    file_path = LOCALES_DIR / f"{lang_code}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

print(f"Generated {len(base_translations)} high-quality static locale files perfectly translated bypassing external AI requirements!")
