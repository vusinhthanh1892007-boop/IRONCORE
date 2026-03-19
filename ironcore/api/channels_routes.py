"""
ironcore/api/channels_routes.py — FastAPI routes for Bot Channel management.

Endpoints:
    GET  /v1/channels/status        — list all channels + running state
    POST /v1/channels/{name}/start  — start a specific channel bot
    POST /v1/channels/{name}/stop   — stop a specific channel bot
    GET  /v1/channels/{name}/health — quick health probe
    POST /v1/webhooks/zalo          — receive Zalo OA webhook events
    POST /v1/webhooks/telegram      — (reserved for future webhook mode)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from ironcore.api.auth import APIKeyAuth, AuthenticatedPrincipal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/channels", tags=["channels"])
webhook_router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

# ─── In-process channel registry ─────────────────────────────────────────────
# Populated lazily on first start request.
_channels: Dict[str, Any] = {}
_channel_tasks: Dict[str, asyncio.Task[None]] = {}


# ─── Response models ──────────────────────────────────────────────────────────

class ChannelStatusResponse(BaseModel):
    name: str
    running: bool
    platform: str
    configured: bool


class StartChannelRequest(BaseModel):
    # Optional override tokens; by default reads from env vars
    access_token: str = ""
    app_secret: str = ""
    refresh_token: str = ""
    verify_token: str = ""       # for Messenger / WhatsApp hub.challenge
    phone_number_id: str = ""   # for WhatsApp Cloud API
    allowed_user_ids: str = ""   # comma-separated


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_configured(name: str) -> bool:
    """Check whether required env vars for a channel are present."""
    if name == "telegram":
        return bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    if name == "zalo":
        return bool(os.getenv("ZALO_OA_ACCESS_TOKEN")) and bool(os.getenv("ZALO_OA_APP_SECRET"))
    if name == "discord":
        return bool(os.getenv("DISCORD_BOT_TOKEN"))
    if name == "messenger":
        return bool(os.getenv("MESSENGER_PAGE_ACCESS_TOKEN")) and bool(os.getenv("MESSENGER_VERIFY_TOKEN"))
    if name == "whatsapp":
        return (
            bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID"))
            and bool(os.getenv("WHATSAPP_ACCESS_TOKEN"))
            and bool(os.getenv("WHATSAPP_VERIFY_TOKEN"))
        )
    return False


def _platform_label(name: str) -> str:
    return {
        "telegram": "Telegram",
        "zalo": "Zalo OA",
        "discord": "Discord",
        "messenger": "Messenger",
        "whatsapp": "WhatsApp",
    }.get(name, name)


def _get_engine(request: Request) -> Any:
    """Get the shared IronCoreEngine from app state."""
    return getattr(request.app.state, "template_engine", None)


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_channels_status(request: Request) -> list[ChannelStatusResponse]:
    """Return running state and configuration status for all supported channels."""
    names = ["telegram", "zalo", "discord", "messenger", "whatsapp"]
    result = []
    for name in names:
        result.append(
            ChannelStatusResponse(
                name=name,
                running=name in _channels and getattr(_channels[name], "_running", False),
                platform=_platform_label(name),
                configured=_is_configured(name),
            )
        )
    return result


@router.post("/{name}/start")
async def start_channel(
    name: str,
    body: StartChannelRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Dict[str, str]:
    """
    Start a bot channel by name.
    Reads credentials from env vars (or body overrides).
    """
    if name not in ("telegram", "zalo", "discord", "messenger", "whatsapp"):
        raise HTTPException(status_code=404, detail=f"Unknown channel: {name}")

    if name in _channels and getattr(_channels[name], "_running", False):
        return {"status": "already_running", "channel": name}

    engine = _get_engine(request)

    try:
        if name == "telegram":
            from ironcore.channels.telegram_bot import TelegramChannel
            token = body.access_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not token:
                raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured.")
            allowed = (
                [int(x) for x in body.allowed_user_ids.split(",") if x.strip().isdigit()]
                if body.allowed_user_ids else []
            )
            channel = TelegramChannel(bot_token=token, allowed_user_ids=allowed, engine=engine)

        elif name == "zalo":
            from ironcore.channels.zalo_bot import ZaloChannel
            token = body.access_token or os.getenv("ZALO_OA_ACCESS_TOKEN", "")
            secret = body.app_secret or os.getenv("ZALO_OA_APP_SECRET", "")
            refresh = body.refresh_token or os.getenv("ZALO_OA_REFRESH_TOKEN", "")
            if not token or not secret:
                raise HTTPException(
                    status_code=400,
                    detail="ZALO_OA_ACCESS_TOKEN and ZALO_OA_APP_SECRET must be configured.",
                )
            allowed = (
                [x.strip() for x in body.allowed_user_ids.split(",") if x.strip()]
                if body.allowed_user_ids else []
            )
            channel = ZaloChannel(
                access_token=token,
                app_secret=secret,
                refresh_token=refresh,
                allowed_user_ids=allowed,
                engine=engine,
            )

        elif name == "discord":
            from ironcore.channels.discord_bot import DiscordChannel
            token = body.access_token or os.getenv("DISCORD_BOT_TOKEN", "")
            if not token:
                raise HTTPException(status_code=400, detail="DISCORD_BOT_TOKEN not configured.")
            channel = DiscordChannel(bot_token=token, engine=engine)

        elif name == "messenger":
            from ironcore.channels.messenger_bot import MessengerChannel
            token = body.access_token or os.getenv("MESSENGER_PAGE_ACCESS_TOKEN", "")
            verify = body.verify_token or os.getenv("MESSENGER_VERIFY_TOKEN", "")
            secret = body.app_secret or os.getenv("MESSENGER_APP_SECRET", "")
            if not token or not verify:
                raise HTTPException(
                    status_code=400,
                    detail="MESSENGER_PAGE_ACCESS_TOKEN and MESSENGER_VERIFY_TOKEN must be configured.",
                )
            allowed = (
                [x.strip() for x in body.allowed_user_ids.split(",") if x.strip()]
                if body.allowed_user_ids else []
            )
            channel = MessengerChannel(
                page_access_token=token,
                verify_token=verify,
                app_secret=secret,
                allowed_psids=allowed,
                engine=engine,
            )

        elif name == "whatsapp":
            from ironcore.channels.whatsapp_bot import WhatsAppChannel
            phone_id = body.phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
            token = body.access_token or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
            verify = body.verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN", "")
            secret = body.app_secret or os.getenv("WHATSAPP_APP_SECRET", "")
            if not phone_id or not token or not verify:
                raise HTTPException(
                    status_code=400,
                    detail="WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, and WHATSAPP_VERIFY_TOKEN must be configured.",
                )
            allowed = (
                [x.strip() for x in body.allowed_user_ids.split(",") if x.strip()]
                if body.allowed_user_ids else []
            )
            channel = WhatsAppChannel(
                phone_number_id=phone_id,
                access_token=token,
                verify_token=verify,
                app_secret=secret,
                allowed_phones=allowed,
                engine=engine,
            )

        else:
            raise HTTPException(status_code=404, detail="Unknown channel.")

    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Channel dependency missing: {exc}")

    _channels[name] = channel

    async def _run_channel() -> None:
        try:
            await channel.start()
        except Exception as exc:
            logger.error("[Channels] %s failed: %s", name, exc, exc_info=True)
            _channels.pop(name, None)

    task = asyncio.create_task(_run_channel())
    _channel_tasks[name] = task
    logger.info("[Channels] %s started.", name)
    return {"status": "started", "channel": name}


@router.post("/{name}/stop")
async def stop_channel(name: str) -> Dict[str, str]:
    """Stop a running bot channel."""
    if name not in _channels:
        return {"status": "not_running", "channel": name}

    channel = _channels.pop(name)
    try:
        await channel.stop()
    except Exception as exc:
        logger.warning("[Channels] Error stopping %s: %s", name, exc)

    task = _channel_tasks.pop(name, None)
    if task and not task.done():
        task.cancel()

    return {"status": "stopped", "channel": name}


@router.get("/{name}/health")
async def channel_health(name: str) -> Dict[str, Any]:
    """Quick health probe for a channel."""
    running = name in _channels and getattr(_channels[name], "_running", False)
    return {"channel": name, "running": running}


# ─── Zalo Webhook receiver ────────────────────────────────────────────────────

@webhook_router.post("/zalo")
async def zalo_webhook(request: Request) -> Dict[str, str]:
    """
    Receive inbound Zalo OA webhook events.

    Zalo sends:
        POST /v1/webhooks/zalo
        X-ZaloOA-Signature: <hmac-sha256-hex>
        Body: JSON event payload
    """
    raw_body = await request.body()
    mac_token = request.headers.get("X-ZaloOA-Signature", "")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    zalo_channel = _channels.get("zalo")
    if zalo_channel is None:
        # Channel not started — still acknowledge to avoid Zalo retry storms
        logger.warning("[Zalo Webhook] Received event but Zalo channel is not running.")
        return {"status": "ok"}

    # Handle asynchronously to return 200 immediately
    asyncio.create_task(
        zalo_channel.handle_webhook_event(payload, mac_token, raw_body=raw_body)
    )
    return {"status": "ok"}


@webhook_router.get("/zalo")
async def zalo_webhook_verify(request: Request) -> Dict[str, str]:
    """
    Zalo OA webhook URL verification (GET probe).
    Zalo sends a GET with ?challenge=xxx and expects {"challenge": xxx} back.
    """
    challenge = request.query_params.get("challenge", "")
    return {"challenge": challenge}


# ─── Messenger Webhook ────────────────────────────────────────────────────────

@webhook_router.post("/messenger")
async def messenger_webhook(request: Request) -> Dict[str, str]:
    """
    Receive Facebook Messenger webhook events.
    Facebook sends:
        POST /v1/webhooks/messenger
        X-Hub-Signature-256: sha256=<hmac>
        Body: JSON with entry[].messaging[]
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    messenger_channel = _channels.get("messenger")
    if messenger_channel is None:
        logger.warning("[Messenger Webhook] Received event but Messenger channel is not running.")
        return {"status": "ok"}

    asyncio.create_task(
        messenger_channel.handle_webhook_event(payload, signature, raw_body=raw_body)
    )
    return {"status": "ok"}


@webhook_router.get("/messenger")
async def messenger_webhook_verify(request: Request) -> Any:
    """
    Facebook hub.challenge verification for Messenger.
    Facebook sends: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    Respond with the challenge value as plain text.
    """
    from fastapi.responses import PlainTextResponse

    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    messenger_channel = _channels.get("messenger")
    if messenger_channel is None:
        raise HTTPException(status_code=403, detail="Messenger channel not started.")

    result = messenger_channel.verify_hub_challenge(mode, token, challenge)
    if result is None:
        raise HTTPException(status_code=403, detail="Verification failed.")
    return PlainTextResponse(result)


# ─── WhatsApp Webhook ─────────────────────────────────────────────────────────

@webhook_router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Dict[str, str]:
    """
    Receive Meta Cloud API WhatsApp webhook events.
    Meta sends:
        POST /v1/webhooks/whatsapp
        X-Hub-Signature-256: sha256=<hmac>
        Body: JSON with entry[].changes[]
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    whatsapp_channel = _channels.get("whatsapp")
    if whatsapp_channel is None:
        logger.warning("[WhatsApp Webhook] Received event but WhatsApp channel is not running.")
        return {"status": "ok"}

    asyncio.create_task(
        whatsapp_channel.handle_webhook_event(payload, signature, raw_body=raw_body)
    )
    return {"status": "ok"}


@webhook_router.get("/whatsapp")
async def whatsapp_webhook_verify(request: Request) -> Any:
    """
    Facebook hub.challenge verification for WhatsApp.
    Meta sends: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    """
    from fastapi.responses import PlainTextResponse

    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    whatsapp_channel = _channels.get("whatsapp")
    if whatsapp_channel is None:
        raise HTTPException(status_code=403, detail="WhatsApp channel not started.")

    result = whatsapp_channel.verify_hub_challenge(mode, token, challenge)
    if result is None:
        raise HTTPException(status_code=403, detail="Verification failed.")
    return PlainTextResponse(result)
