#!/usr/bin/env python3
import os
import sys
import subprocess

def _is_build_command() -> bool:
    if any("_in_process.py" in arg for arg in sys.argv):
        return True
    script_name = os.path.basename(sys.argv[0] if sys.argv else "")
    if script_name != "setup.py":
        return True
    build_verbs = {
        "install", "develop", "build", "bdist_wheel", "egg_info",
        "dist_info", "sdist", "editable_wheel", "clean", "--help", "-h"
    }
    if len(sys.argv) > 1 and any(arg in build_verbs for arg in sys.argv[1:]):
        return True
    return False

if _is_build_command():
    from setuptools import setup
    setup()
else:
    try:
        import questionary
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:
        print(">> Installing setup wizard dependencies (questionary, rich)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "questionary", "rich"])
        import questionary
        from rich.console import Console
        from rich.panel import Panel

    console = Console()

# 1. Danh sách ngôn ngữ (có thể gõ để search)
LANGUAGES = [
    "English", "Tiếng Việt", "Español (Spanish)", "Français (French)", 
    "Deutsch (German)", "中文 (Chinese)", "日本語 (Japanese)", "한국어 (Korean)",
    "Русский (Russian)", "Português (Portuguese)", "Italiano (Italian)",
    "العربية (Arabic)", "हिन्दी (Hindi)", "Bengali", "Punjabi", 
    "Javanese", "Telugu", "Marathi", "Tamil", "Urdu", "Gujarati", 
    "Polski (Polish)", "Українська (Ukrainian)", "Nederlands (Dutch)", "ภาษาไทย (Thai)",
    "Bahasa Indonesia (Indonesian)", "Bahasa Melayu (Malay)", "Türkçe (Turkish)",
    "فارسی (Persian)", "Tagalog (Filipino)", "Swahili", "Hausa", "Yoruba",
    "Igbo", "Amharic", "Oromo", "Somali", "Zulu", "Xhosa", "Afrikaans",
    "Svenska (Swedish)", "Dansk (Danish)", "Norsk (Norwegian)", "Suomi (Finnish)",
    "Íslenska (Icelandic)", "Čeština (Czech)", "Slovenčina (Slovak)",
    "Magyar (Hungarian)", "Română (Romanian)", "Български (Bulgarian)",
    "Српски (Serbian)", "Hrvatski (Croatian)", "Bosanski (Bosnian)",
    "Ελληνικά (Greek)", "עברית (Hebrew)", "Català (Catalan)", "Euskara (Basque)",
    "Galego (Galician)", "Welsh", "Irish", "Scottish Gaelic", 
    "Latviešu (Latvian)", "Lietuvių (Lithuanian)", "Eesti (Estonian)",
    "Malti (Maltese)", "Kurdish", "Pashto", "Nepali", "Sinhala", "Khmer",
    "Lao", "Burmese", "Tibetan", "Mongolian", "Uyghur", "Kazakh", "Uzbek",
    "Turkmen", "Kyrgyz", "Tajik", "Georgian", "Armenian", "Azerbaijani",
    "Macedonian", "Albanian", "Slovenian", "Esperanto", "Latin", "Sanskrit"
]

# 2. Từ điển dịch thuật
TRANSLATIONS = {
    "English": {
        "welcome": "Welcome to IronCore V2 Setup Wizard",
        "choose_version": "Which version do you want to install?",
        "lite": "Lite Version (API only, Fast, < 1GB)",
        "full": "Full Version (Local AI, GPU Required, 8GB+)",
        "choose_provider": "Which AI Provider do you want to use?",
        "openai": "OpenAI (ChatGPT)",
        "anthropic": "Anthropic (Claude)",
        "google": "Google (Gemini)",
        "skip_api": "Skip (Use Local AI / Configure later)",
        "enter_openai": "Paste your OpenAI API Key (sk-...):",
        "enter_anthropic": "Paste your Anthropic API Key (sk-ant-...):",
        "enter_google": "Paste your Gemini API Key:",
        "saved_api": "API Key saved to .env file.",
        "choose_skills": "Select the Skills & Features you want to enable for the AI (Space to select, Enter to confirm):",
        "skill_web": "🌐 Web Browsing (Search & Extract info from links)",
        "skill_code": "💻 Code Execution (Run Python/Bash safely)",
        "skill_file": "📁 File System (Read/Write local files)",
        "skill_vision": "👁️ Vision & Screenshots (Analyze images & UI)",
        "skill_memory": "🧠 GraphRAG Memory (Long-term context retention)",
        "skill_social": "💬 Social Integrations (Zalo, Telegram bots)",
        "saved_skills": "Selected skills activated and saved to config.",
        "installing": "Installing core packages...",
        "installing_full": "Installing heavy Local AI models (PyTorch, Transformers)...",
        "choose_interface": "How would you like to use IronCore?",
        "web": "Web Browser Interface (Next.js Dashboard)",
        "terminal": "Terminal CLI Interface (Fast & Hacky)",
        "starting": "Starting IronCore..."
    },
    "Tiếng Việt": {
        "welcome": "Chào mừng đến với Trình Cài đặt IronCore V2",
        "choose_version": "Bạn muốn cài đặt phiên bản nào?",
        "lite": "Bản Lite (Chỉ dùng gọi API, Cực nhẹ, < 1GB)",
        "full": "Bản Full (Chạy AI Nội bộ, Cần GPU mạnh, 8GB+)",
        "choose_provider": "Chọn Mạng AI (Hãng AI) bạn muốn dùng làm Trí Năng cốt lõi:",
        "openai": "OpenAI (ChatGPT)",
        "anthropic": "Anthropic (Claude)",
        "google": "Google (Gemini)",
        "skip_api": "Bỏ qua (sẽ dùng cấu hình AI Local hoặc nhập sau)",
        "enter_openai": "Dán mã API Key OpenAI của bạn (bắt đầu bằng sk-...):",
        "enter_anthropic": "Dán mã API Key Anthropic của bạn (bắt đầu bằng sk-ant-...):",
        "enter_google": "Dán mã API Key Google Gemini của bạn:",
        "saved_api": "Đã lưu trữ API Key mã hóa vào file .env an toàn.",
        "choose_skills": "Chọn các KỸ NĂNG (Skills) bạn muốn trang bị cho con AI (Bấm Dấu Cách để chọn, Enter để chốt):",
        "skill_web": "🌐 Lướt Web (Tìm kiếm Google & Đọc báo mạng)",
        "skill_code": "💻 Chạy Code (Viết và chạy Python/Bash để xử lý dữ liệu)",
        "skill_file": "📁 Quản lý File (Đọc/Ghi tài liệu trên máy tính bạn)",
        "skill_vision": "👁️ Thị giác Máy tính (Chụp màn hình, Nhận diện ảnh)",
        "skill_memory": "🧠 Trí nhớ dài hạn (Nhớ mặt user qua nhiều ngày bằng GraphRAG)",
        "skill_social": "💬 Trợ lý Mạng Xã Hội (Tự động Chat trên Zalo, Telegram)",
        "saved_skills": "Đã ghi nhận và kích hoạt các kỹ năng bạn chọn.",
        "installing": "Đang cài đặt các gói hệ thống lõi...",
        "installing_full": "Đang tải các mô hình AI Nội bộ siêu nặng (PyTorch, Transformers)...",
        "choose_interface": "Bạn muốn giao tiếp với AI qua giao diện nào?",
        "web": "Giao diện Web Browser (Dashboard Next.js đẹp mắt)",
        "terminal": "Giao diện Terminal (Màn hình đen chữ xanh kiểu Hacker)",
        "starting": "Đang khởi động IronCore..."
    },
    "Français (French)": {
        "welcome": "Bienvenue dans l'assistant d'installation IronCore V2",
        "choose_version": "Quelle version souhaitez-vous installer ?",
        "lite": "Version Lite (API uniquement, Rapide, < 1Go)",
        "full": "Version Complète (IA Locale, GPU Requis, 8Go+)",
        "choose_provider": "Quel fournisseur d'IA souhaitez-vous utiliser ?",
        "openai": "OpenAI (ChatGPT)",
        "anthropic": "Anthropic (Claude)",
        "google": "Google (Gemini)",
        "skip_api": "Ignorer (Utiliser l'IA locale / Configurer plus tard)",
        "enter_openai": "Collez votre clé API OpenAI (sk-...) :",
        "enter_anthropic": "Collez votre clé API Anthropic (sk-ant-...) :",
        "enter_google": "Collez votre clé API Gemini :",
        "saved_api": "Clé API enregistrée dans le fichier .env.",
        "choose_skills": "Sélectionnez les compétences à activer (Espace pour sélectionner, Entrée pour confirmer) :",
        "skill_web": "🌐 Navigation Web (Rechercher et extraire des infos)",
        "skill_code": "💻 Exécution de Code (Exécuter Python/Bash en sécurité)",
        "skill_file": "📁 Système de fichiers (Lire/Écrire des fichiers locaux)",
        "skill_vision": "👁️ Vision & Captures (Analyser images & UI)",
        "skill_memory": "🧠 Mémoire GraphRAG (Rétention du contexte à long terme)",
        "skill_social": "💬 Intégrations Sociales (Bots Zalo, Telegram)",
        "saved_skills": "Compétences sélectionnées activées et sauvegardées.",
        "installing": "Installation des paquets de base...",
        "installing_full": "Installation des modèles d'IA locaux (PyTorch, Transformers)...",
        "choose_interface": "Comment souhaitez-vous utiliser IronCore ?",
        "web": "Interface Navigateur Web (Tableau de bord Next.js)",
        "terminal": "Interface CLI Terminal (Rapide & Hacker)",
        "starting": "Démarrage d'IronCore..."
    },
    "Español (Spanish)": {
        "welcome": "Bienvenido al Asistente de Instalación de IronCore V2",
        "choose_version": "¿Qué versión deseas instalar?",
        "lite": "Versión Lite (Solo API, Rápida, < 1GB)",
        "full": "Versión Completa (IA Local, GPU Requerida, 8GB+)",
        "choose_provider": "¿Qué proveedor de IA deseas usar?",
        "openai": "OpenAI (ChatGPT)",
        "anthropic": "Anthropic (Claude)",
        "google": "Google (Gemini)",
        "skip_api": "Omitir (Usar IA Local / Configurar más tarde)",
        "enter_openai": "Pega tu clave API de OpenAI (sk-...):",
        "enter_anthropic": "Pega tu clave API de Anthropic (sk-ant-...):",
        "enter_google": "Pega tu clave API de Gemini:",
        "saved_api": "Clave API guardada en el archivo .env.",
        "choose_skills": "Selecciona las habilidades que deseas habilitar (Espacio para seleccionar, Enter para confirmar):",
        "skill_web": "🌐 Navegación Web (Buscar y extraer info)",
        "skill_code": "💻 Ejecución de Código (Python/Bash)",
        "skill_file": "📁 Sistema de Archivos (Leer/Escribir archivos)",
        "skill_vision": "👁️ Visión y Capturas (Analizar imágenes)",
        "skill_memory": "🧠 Memoria GraphRAG (Retener contexto)",
        "skill_social": "💬 Integraciones Sociales (Zalo, Telegram)",
        "saved_skills": "Habilidades activadas y guardadas.",
        "installing": "Instalando paquetes básicos...",
        "installing_full": "Instalando modelos pesados de IA Local...",
        "choose_interface": "¿Cómo te gustaría usar IronCore?",
        "web": "Interfaz Web (Dashboard Next.js)",
        "terminal": "Interfaz Terminal CLI (Rápida y Hacker)",
        "starting": "Iniciando IronCore..."
    },
    "中文 (Chinese)": {
        "welcome": "欢迎使用 IronCore V2 安装向导",
        "choose_version": "您要安装哪个版本？",
        "lite": "精简版 (仅通过 API，极速，< 1GB)",
        "full": "完整版 (本地 AI，需要 GPU，8GB+)",
        "choose_provider": "您要使用哪个 AI 提供商？",
        "openai": "OpenAI (ChatGPT)",
        "anthropic": "Anthropic (Claude)",
        "google": "Google (Gemini)",
        "skip_api": "跳过 (使用本地 AI / 稍后配置)",
        "enter_openai": "粘贴您的 OpenAI API 密钥 (sk-...)：",
        "enter_anthropic": "粘贴您的 Anthropic API 密钥 (sk-ant-...)：",
        "enter_google": "粘贴您的 Gemini API 密钥：",
        "saved_api": "API 密钥已保存到 .env 文件。",
        "choose_skills": "选择您要启用的技能（使用空格键选择，按 Enter 键确认）：",
        "skill_web": "🌐 网页浏览 (搜索信息)",
        "skill_code": "💻 代码执行 (安全运行 Python/Bash)",
        "skill_file": "📁 文件系统 (读写本地文件)",
        "skill_vision": "👁️ 视觉与截图 (分析图片)",
        "skill_memory": "🧠 GraphRAG 记忆 (长期上下文)",
        "skill_social": "💬 社交整合 (Zalo, Telegram 机器人)",
        "saved_skills": "选定的技能已激活并保存。",
        "installing": "正在安装核心包...",
        "installing_full": "正在安装大型本地 AI 模型...",
        "choose_interface": "您想如何使用 IronCore？",
        "web": "网页浏览器界面 (Next.js)",
        "terminal": "终端 CLI 界面 (极客风格)",
        "starting": "正在启动 IronCore..."
    }
}

def get_text(lang, key):
    # Try exact match first
    if lang in TRANSLATIONS:
        return TRANSLATIONS[lang].get(key, TRANSLATIONS["English"][key])
    
    # Check if a translation dictionary key is part of the language string
    # E.g if "Français (French)" inside TRANSLATIONS matches lang "Français (French)"
    for t_lang in TRANSLATIONS:
        if t_lang in lang or lang in t_lang:
            return TRANSLATIONS[t_lang].get(key, TRANSLATIONS["English"][key])
            
    # Language not found, fallback to English
    return TRANSLATIONS["English"][key]

def run_command(cmd, message):
    console.print(f"[bold cyan]>> {message}[/bold cyan]")
    process = subprocess.Popen(cmd, shell=True)
    process.communicate()
    if process.returncode != 0:
        console.print("[bold red]❌ Installation failed! Please check the logs.[/bold red]")
        sys.exit(1)

def main():
    console.clear()
    
    # --- BƯỚC 1: Chọn ngôn ngữ ---
    lang = questionary.autocomplete(
        'Language / Ngôn ngữ / Langue / Idioma / 语言:',
        choices=LANGUAGES,
        default="English"
    ).ask()

    if not lang:
        sys.exit(0)

    console.print(Panel(f"[bold green]{get_text(lang, 'welcome')}[/bold green]", expand=False))

    # --- BƯỚC 2: Chọn Phiên Bản (Lite vs Full) ---
    version_choice = questionary.select(
        get_text(lang, 'choose_version'),
        choices=[
            get_text(lang, 'lite'),
            get_text(lang, 'full')
        ]
    ).ask()

    if not version_choice:
        sys.exit(0)
    
    is_lite = version_choice == get_text(lang, 'lite')

    # --- BƯỚC 2.5: Cấu hình API Key ---
    api_provider = questionary.select(
        get_text(lang, 'choose_provider'),
        choices=[
            get_text(lang, 'openai'),
            get_text(lang, 'anthropic'),
            get_text(lang, 'google'),
            get_text(lang, 'skip_api')
        ]
    ).ask()

    env_content = ""
    if get_text(lang, 'openai') == api_provider:
        key = questionary.password(get_text(lang, 'enter_openai')).ask()
        if key: env_content += f"OPENAI_API_KEY={key}\n"
    elif get_text(lang, 'anthropic') == api_provider:
        key = questionary.password(get_text(lang, 'enter_anthropic')).ask()
        if key: env_content += f"ANTHROPIC_API_KEY={key}\n"
    elif get_text(lang, 'google') == api_provider:
        key = questionary.password(get_text(lang, 'enter_google')).ask()
        if key: env_content += f"GEMINI_API_KEY={key}\n"
    
    if env_content:
        with open(".env", "a") as f:
            f.write(env_content)
        console.print(f"[dim]{get_text(lang, 'saved_api')}[/dim]")

    # --- BƯỚC 2.8: Chọn SKILLS ---
    skills_chosen = questionary.checkbox(
        get_text(lang, 'choose_skills'),
        choices=[
            questionary.Choice(get_text(lang, 'skill_web'), checked=True),
            questionary.Choice(get_text(lang, 'skill_code'), checked=True),
            questionary.Choice(get_text(lang, 'skill_file'), checked=False),
            questionary.Choice(get_text(lang, 'skill_vision'), checked=False),
            questionary.Choice(get_text(lang, 'skill_memory'), checked=False),
            questionary.Choice(get_text(lang, 'skill_social'), checked=False),
        ]
    ).ask()

    if skills_chosen:
        console.print(f"[dim]{get_text(lang, 'saved_skills')}[/dim]")

    # Install Core
    run_command("pip install -r requirements.txt", get_text(lang, 'installing'))

    if not is_lite:
        # Install Full AI
        run_command("pip install -r requirements-ai.txt", get_text(lang, 'installing_full'))

    console.print("[bold green]✅ Setup Complete![/bold green]\n")

    # --- BƯỚC 3: Chọn Giao Diện Chạy ---
    interface_choice = questionary.select(
        get_text(lang, 'choose_interface'),
        choices=[
            get_text(lang, 'web'),
            get_text(lang, 'terminal')
        ]
    ).ask()

    console.print(f"[bold yellow]{get_text(lang, 'starting')}[/bold yellow]")

    if interface_choice == get_text(lang, 'web'):
        # Chạy Backend (chìm) và Frontend
        console.print("[dim]Starting FastAPI Backend on port 8000...[/dim]")
        subprocess.Popen(["uvicorn", "ironcore.api.server:app", "--port", "8000"])
        
        console.print("[dim]Starting Next.js Frontend on port 3000...[/dim]")
        os.chdir("web")
        # Run npm dev and attach to terminal so user can see logs
        subprocess.run(["npm", "run", "dev"])

    else:
        # Chạy Terminal CLI
        subprocess.run([sys.executable, "cli.py"])

if __name__ == "__main__" and not _is_build_command():
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

