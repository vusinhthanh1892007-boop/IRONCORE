from ironcore.tui.i18n import i18n
from textual.app import ComposeResult
from textual.widgets import Header, Footer, Label, RadioSet, RadioButton
from textual.containers import VerticalScroll
from ironcore.tui.screens.base import BaseWizardScreen

class ChannelScreen(BaseWizardScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="content-container"):
            yield Label(i18n.t("Select Messaging Channel"), id="step-title")
            yield Label(i18n.t("Choose the primary platform your agent will operate on:"))
            
            with RadioSet(id="channel-mode"):
                yield RadioButton(i18n.t("Telegram (Bot API) - recommended"), id="telegram", value=True)
                yield RadioButton(i18n.t("WhatsApp (QR link)"), id="whatsapp")
                yield RadioButton(i18n.t("Discord (Bot API)"), id="discord")
                yield RadioButton(i18n.t("IRC (Server + Nick)"), id="irc")
                yield RadioButton(i18n.t("Google Chat (Chat API)"), id="gchat")
                yield RadioButton(i18n.t("Slack (Socket Mode)"), id="slack")
                yield RadioButton(i18n.t("Signal (signal-cli)"), id="signal")
                yield RadioButton(i18n.t("iMessage (imsg)"), id="imessage")
                yield RadioButton(i18n.t("LINE (Messaging API)"), id="line")
                yield RadioButton(i18n.t("Feishu/Lark (飞书)"), id="feishu")
                yield RadioButton(i18n.t("Nostr (NIP-04 DMs)"), id="nostr")
                yield RadioButton(i18n.t("Microsoft Teams (Bot Framework)"), id="teams")
                yield RadioButton(i18n.t("Mattermost (plugin)"), id="mattermost")
                yield RadioButton(i18n.t("Nextcloud Talk (webhook)"), id="nextcloud")
                yield RadioButton(i18n.t("Matrix (plugin)"), id="matrix")
                yield RadioButton(i18n.t("BlueBubbles (macOS app)"), id="bluebubbles")
                yield RadioButton(i18n.t("Zalo (Bot API)"), id="zalo_bot")
                yield RadioButton(i18n.t("Zalo (Personal Account)"), id="zalo_personal")
                yield RadioButton(i18n.t("Synology Chat (Webhook)"), id="synology")
                yield RadioButton(i18n.t("Tlon (Urbit)"), id="tlon")
                
            yield from self.compose_navigation()
        yield Footer()

    def on_next(self) -> None:
        channel = self.query_one("#channel-mode", RadioSet).pressed_button.id
        self.app.cfg["channel"] = channel
        self.dismiss("skills")
