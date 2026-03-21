import json
from pathlib import Path

LOCALES_DIR = Path("/home/vusinhthanh/train ai/ironcore/tui/locales")
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

with open("/tmp/unique_keys.json", "r") as f:
    keys = json.load(f)

# accurate Vietnamese
vi = {
  "Welcome & Preflight Check": "Chào mừng & Kiểm duyệt",
  "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_": "**IronCore Setup Wizard** sẽ cấu hình môi trường AI Agent nội bộ.\n\n  * Nhà cung cấp models & API keys\n  * Dịch vụ Gateway & Chính sách bộ nhớ\n  * Persona của Agent & Hooks\n\n_Thời gian ước tính: 3-5 phút_",
  "🖥  OS:": "🖥  Hệ điều hành:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Mạng:",
  "[green]Online ✓[/]": "[green]Hoạt động ✓[/]", "[red]Offline ✗[/]": "[red]Mất kết nối ✗[/]",
  "Authentication": "Xác thực", "Model Provider(s)": "Nhà cung cấp Mô hình", "Back": "Quay lại", "Next": "Tiếp theo",
  "Select your authentication mode:": "Chọn chế độ xác thực:",
  "Local only — no account, config saved to ~/.ironcore": "Chỉ nội bộ — không tài khoản, lưu tại ~/.ironcore",
  "Cloud Token — sync settings across devices": "Cloud Token — đồng bộ cài cài đặt trên các thiết bị",
  "Configuration Exported successfully! (~/.ironcore/config.json)": "Cấu hình đã xuất thành công! (~/.ironcore/config.json)",
  "Configure webhook events (e.g., on_message, on_error)": "Cấu hình sự kiện webhook (VD: on_message, on_error)",
  "Enable skills for your AI Agent:\n": "Kích hoạt kỹ năng cho AI Agent:\n",
  "EXPORT & START": "XUẤT & KHỞI CHẠY",
  "Gateway & Runtime Server": "Gateway & Máy chủ Runtime",
  "Primary Model Selection (Live from Web)": "Chọn Mô hình chính (Trực tiếp từ Web)",
  "Run Smoke Test": "Chạy Smoke Test", "Skills & Plugins": "Kỹ năng & Tiện ích",
  "Summary & Deploy": "Tóm tắt & Khởi chạy", "Token & Secrets": "Token & Bảo mật"
}

# Accurate Spanish
es = {
  "Welcome & Preflight Check": "Vérification et Contrôle préliminaire",
  "Welcome & Preflight Check": "Bienvenido y Control Previo",
  "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_": "**IronCore Setup Wizard** configurará el tiempo de ejecución de su agente de IA local.\n\n  * Proveedores de modelos y claves API\n  * Servicio de Gateway y política de memoria\n  * Persona y ganchos del agente\n\n_Tiempo estimado: 3-5 minutos_",
  "🖥  OS:": "🖥  Hệ điều hành:", "🖥  OS:": "🖥  Sistema Operativo:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Red:",
  "[green]Online ✓[/]": "[green]Conectado ✓[/]", "[red]Offline ✗[/]": "[red]Desconectado ✗[/]",
  "Authentication": "Autenticación", "Model Provider(s)": "Proveedores de Modelos", "Back": "Atrás", "Next": "Siguiente",
  "Select your authentication mode:": "Seleccione su modo de autenticación:",
  "Local only — no account, config saved to ~/.ironcore": "Solo local — sin cuenta, configuración guardada en ~/.ironcore",
  "Cloud Token — sync settings across devices": "Token en la nube — sincronizar configuraciones entre dispositivos",
  "Configuration Exported successfully! (~/.ironcore/config.json)": "¡Configuración exportada con éxito! (~/.ironcore/config.json)",
  "EXPORT & START": "EXPORTAR Y INICIAR", "Gateway & Runtime Server": "Servidor Gateway y Runtime",
  "Primary Model Selection (Live from Web)": "Selección de Modelo Principal", "Run Smoke Test": "Ejecutar Prueba de Humo",
  "Skills & Plugins": "Habilidades y Plugins", "Summary & Deploy": "Resumen y Despliegue", "Token & Secrets": "Token y Secretos"
}

# Accurate German
de = {
  "Welcome & Preflight Check": "Willkommen & Systemprüfung",
  "**IronCore Setup Wizard** will configure your local AI agent runtime.\n\n  * Model providers & API keys\n  * Gateway service & Memory policy\n  * Agent persona & Hooks\n\n_Estimated time: 3-5 minutes_": "**IronCore Setup Wizard** konfiguriert die Laufzeitumgebung Ihres lokalen KI-Agenten.\n\n  * Modellanbieter & API-Schlüssel\n  * Gateway-Dienst & Speicherrichtlinie\n  * Agenten-Persona & Hooks\n\n_Geschätzte Zeit: 3-5 Minuten_",
  "🖥  OS:": "🖥  System:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Netzwerk:",
  "[green]Online ✓[/]": "[green]Online ✓[/]", "[red]Offline ✗[/]": "[red]Offline ✗[/]",
  "Authentication": "Authentifizierung", "Model Provider(s)": "Modellanbieter", "Back": "Zurück", "Next": "Weiter",
  "Select your authentication mode:": "Authentifizierungsmodus wählen:",
  "Local only — no account, config saved to ~/.ironcore": "Nur lokal — kein Account, Konfiguration in ~/.ironcore gespeichert",
  "Cloud Token — sync settings across devices": "Cloud Token — Einstellungen synchronisieren",
  "EXPORT & START": "EXPORTIEREN & STARTEN", "Gateway & Runtime Server": "Gateway & Laufzeit-Server",
  "Primary Model Selection (Live from Web)": "Primäre Modellauswahl", "Run Smoke Test": "Smoke-Test ausführen",
  "Skills & Plugins": "Fähigkeiten & Plugins", "Summary & Deploy": "Zusammenfassung & Bereitstellen", "Token & Secrets": "Token & Geheimnisse"
}

# Accurate French
fr = {
  "Welcome & Preflight Check": "Contrôle préliminaire",
  "Authentication": "Authentification", "Model Provider(s)": "Fournisseurs de Modèles", "Back": "Retour", "Next": "Suivant",
  "🖥  OS:": "🖥  Système d'exploitation:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Réseau:",
  "[green]Online ✓[/]": "[green]En ligne ✓[/]", "[red]Offline ✗[/]": "[red]Hors ligne ✗[/]",
  "Select your authentication mode:": "Sélectionnez votre mode d'identification:",
  "EXPORT & START": "EXPORTER & LANCER", "Gateway & Runtime Server": "Serveur de Passerelle",
  "Run Smoke Test": "Lancer le Test", "Skills & Plugins": "Compétences & Plugins", "Summary & Deploy": "Résumé & Déployer"
}

# Accurate Italian
it = {
  "Welcome & Preflight Check": "Controllo Prelilinare",
  "Authentication": "Autenticazione", "Model Provider(s)": "Fornitori di Modelli", "Back": "Indietro", "Next": "Avanti",
  "🖥  OS:": "🖥  OS:", "🐍 Python:": "🐍 Python:", "🌐 Network:": "🌐 Rete:",
  "[green]Online ✓[/]": "[green]Online ✓[/]", "[red]Offline ✗[/]": "[red]Offline ✗[/]",
  "Select your authentication mode:": "Seleziona modalità di autenticazione:"
}

codes = [ "en", "vi", "es", "de", "fr", "it", "ko", "ja", "ru", "pt" ]
maps = { "vi": vi, "es": es, "de": de, "fr": fr, "it": it }

for code in codes:
    file_path = LOCALES_DIR / f"{code}.json"
    if code == "en":
        data = {k: k for k in keys}
    else:
        src_map = maps.get(code, vi if code == "vi" else {})
        data = {}
        for k in keys:
            data[k] = src_map.get(k, k) # default to English string k
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

print("Generated Part 1 accurate static dictionaries statically.")
