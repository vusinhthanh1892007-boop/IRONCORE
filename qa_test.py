import sys
import os
import asyncio
import traceback

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from ironcore.tui.app import IronCoreTUI

async def run_qa():
    app = IronCoreTUI()
    log = []
    def record(msg):
        log.append(msg)
        print(msg)

    try:
        async with app.run_test() as pilot:
            record("=== BẮT ĐẦU QA TEST TUI V3 (INTEGRATION TEST) ===")
            
            # 1. LanguageScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            record(" -> Simulating selection: 'en'")
            app.screen.dismiss("en")
            await pilot.pause(0.2)
            
            # 2. PreflightScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "PreflightScreen", "Routing failed!"
            record(" -> Simulating 'Next' button")
            app.screen.dismiss("auth")
            await pilot.pause(0.2)

            # 3. AuthScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "AuthScreen"
            app.cfg["auth"] = {"mode": "cloud", "token_present": True}
            app.screen.dismiss("search")
            await pilot.pause(0.2)

            # 4. SearchProviderScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "SearchProviderScreen"
            app.cfg["search"] = {"provider": "brave", "has_key": False}
            app.screen.dismiss("providers")
            await pilot.pause(0.2)

            # 5. ModelProvidersScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "ModelProvidersScreen"
            app.cfg["providers"] = ["openai"]
            app.screen.dismiss("model_picker")
            await pilot.pause(0.2)

            # 6. ModelPickerScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "ModelPickerScreen"
            app.cfg["primary_model"] = "gpt-4o"
            app.screen.dismiss("channels")
            await pilot.pause(0.2)

            # 7. ChannelScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "ChannelScreen"
            app.cfg["channel"] = "telegram"
            app.screen.dismiss("skills")
            await pilot.pause(0.2)

            # 8. SkillsScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "SkillsScreen"
            app.cfg["skills"] = ["web_search"]
            app.screen.dismiss("hooks")
            await pilot.pause(0.2)

            # 9. HooksScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "HooksScreen"
            app.cfg["hooks"] = {"enabled": True, "url": "http://lo", "has_secret": False}
            app.screen.dismiss("gateway")
            await pilot.pause(0.2)

            # 10. GatewayScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "GatewayScreen"
            app.cfg["gateway"] = {"port": "8000", "bind": "bind-local"}
            app.screen.dismiss("secrets")
            await pilot.pause(0.2)

            # 11. SecretsScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "SecretsScreen"
            app.cfg["secrets_acked"] = True
            app.screen.dismiss("persona")
            await pilot.pause(0.2)

            # 12. PersonaScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "PersonaScreen"
            app.cfg["persona"] = {"name": "Test", "prompt": "P", "memory": "persistent"}
            app.screen.dismiss("monitoring")
            await pilot.pause(0.2)

            # 13. MonitoringScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "MonitoringScreen"
            app.cfg["monitoring"] = {"telemetry": True, "backup": "daily"}
            app.screen.dismiss("final")
            await pilot.pause(0.2)

            # 14. FinalSmokeTestScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "FinalSmokeTestScreen"
            app.screen.dismiss("deploy")
            await pilot.pause(0.2)

            # 15. SummaryExportScreen
            record(f"[+] Current: {app.screen.__class__.__name__}")
            assert app.screen.__class__.__name__ == "SummaryExportScreen"
            app.screen.dismiss("done")
            await pilot.pause(0.2)
            
            record("\n=== APP CONFIG THU ĐƯỢC ===")
            record(str(app.cfg))
            record("=== KHÔNG CÓ CRASH! TUI CHẠY MƯỢT TỪ ĐẦU TỚI CUỐI ===")

    except Exception as e:
        record(f"\n[!!!] 💥 PHÁT HIỆN LỖ HỔNG HOẶC CRASH: {e}")
        record(traceback.format_exc())

    with open("/tmp/qa_report2.txt", "w") as f:
        f.write("\n".join(log))

if __name__ == "__main__":
    asyncio.run(run_qa())
