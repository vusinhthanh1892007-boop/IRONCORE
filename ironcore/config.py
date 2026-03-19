"""
IronCore Centralized Configuration — Fix for scattered env vars.

Thay vì mỗi module đọc os.environ trực tiếp, dùng class này làm
single source of truth cho toàn bộ environment configuration.

Usage:
    from ironcore.config import cfg
    threshold = cfg.firewall_burst_threshold
    cidr = cfg.airgap_allowed_cidrs
"""

from __future__ import annotations

import os
from typing import List


class IronCoreConfig:
    """Centralized configuration from environment variables."""

    # ── Edition ──────────────────────────────────────────────────────────────
    @property
    def edition(self) -> str:
        return os.environ.get("IRONCORE_EDITION", "community")

    @property
    def is_enterprise(self) -> bool:
        return self.edition.lower() == "enterprise"

    # ── Auth ─────────────────────────────────────────────────────────────────
    @property
    def api_key(self) -> str:
        return os.environ.get("IRONCORE_API_KEY", "")

    @property
    def admin_api_key(self) -> str:
        return os.environ.get("IRONCORE_ADMIN_API_KEY", "")

    @property
    def require_auth_on_enterprise(self) -> bool:
        """If True, /api/enterprise/* routes require X-Api-Key header."""
        return os.environ.get("IRONCORE_ENTERPRISE_AUTH_REQUIRED", "true").lower() not in ("false", "0", "no")

    # ── Firewall ──────────────────────────────────────────────────────────────
    @property
    def firewall_quarantine_threshold(self) -> int:
        return int(os.environ.get("IRONCORE_FIREWALL_QUARANTINE_THRESHOLD", "5"))

    @property
    def firewall_quarantine_ttl(self) -> int:
        return int(os.environ.get("IRONCORE_FIREWALL_QUARANTINE_TTL", "300"))

    @property
    def firewall_rules_path(self) -> str:
        return os.environ.get("IRONCORE_FIREWALL_RULES_PATH", "")

    @property
    def firewall_siem_enabled(self) -> bool:
        return os.environ.get("IRONCORE_FIREWALL_SIEM_ENABLED", "true").lower() not in ("false", "0")

    # ── SIEM ──────────────────────────────────────────────────────────────────
    @property
    def siem_transports(self) -> List[str]:
        raw = os.environ.get("IRONCORE_SIEM_TRANSPORTS", "splunk")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def siem_buffer_size(self) -> int:
        return int(os.environ.get("IRONCORE_SIEM_BUFFER_SIZE", "10000"))

    @property
    def siem_flush_interval(self) -> float:
        return float(os.environ.get("IRONCORE_SIEM_FLUSH_INTERVAL", "2.0"))

    @property
    def siem_hostname(self) -> str:
        return os.environ.get("IRONCORE_SIEM_HOSTNAME", "ironcore")

    @property
    def siem_failsafe_path(self) -> str:
        return os.environ.get("IRONCORE_SIEM_FAILSAFE_PATH", "/var/log/ironcore/siem-failsafe.log")

    # ── Airgap ────────────────────────────────────────────────────────────────
    @property
    def airgap_enabled(self) -> bool:
        return os.environ.get("IRONCORE_AIRGAP_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def airgap_allow_external(self) -> bool:
        return os.environ.get("IRONCORE_AIRGAP_ALLOW_EXTERNAL", "false").lower() in ("true", "1")

    @property
    def airgap_allowed_cidrs(self) -> List[str]:
        raw = os.environ.get("IRONCORE_AIRGAP_ALLOWED_CIDRS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
        return [c.strip() for c in raw.split(",") if c.strip()]

    @property
    def airgap_allowed_models(self) -> List[str]:
        raw = os.environ.get("IRONCORE_AIRGAP_ALLOWED_MODELS", "llama3.1:8b,llama3.1:70b,mistral:7b,phi3:mini")
        return [m.strip() for m in raw.split(",") if m.strip()]

    @property
    def airgap_db_path(self) -> str:
        return os.environ.get("IRONCORE_AIRGAP_DB_PATH", "/tmp/ironcore_airgap.db")

    # ── Monitoring / Anomaly Detection ────────────────────────────────────────
    @property
    def alert_db_path(self) -> str:
        return os.environ.get("IRONCORE_ALERT_DB_PATH", "/tmp/ironcore_alerts.db")

    @property
    def alert_eval_interval(self) -> float:
        return float(os.environ.get("IRONCORE_ALERT_EVAL_INTERVAL", "30.0"))

    @property
    def alert_webhook_url(self) -> str:
        return os.environ.get("IRONCORE_ALERT_WEBHOOK_URL", "")

    @property
    def thresh_fw_burst(self) -> int:
        return int(os.environ.get("IRONCORE_THRESH_FW_BURST", "10"))

    @property
    def thresh_err_rate(self) -> float:
        return float(os.environ.get("IRONCORE_THRESH_ERR_RATE", "0.5"))

    @property
    def thresh_gr_violations(self) -> int:
        return int(os.environ.get("IRONCORE_THRESH_GR_VIOL", "5"))

    @property
    def thresh_sessions(self) -> int:
        return int(os.environ.get("IRONCORE_THRESH_SESSIONS", "50"))

    @property
    def thresh_cooldown(self) -> int:
        return int(os.environ.get("IRONCORE_THRESH_COOLDOWN", "300"))

    # ── SSO ──────────────────────────────────────────────────────────────────
    @property
    def sso_provider(self) -> str:
        return os.environ.get("IRONCORE_SSO_PROVIDER", "oidc")

    @property
    def sso_client_id(self) -> str:
        return os.environ.get("IRONCORE_SSO_CLIENT_ID", "")

    @property
    def sso_redirect_uri(self) -> str:
        return os.environ.get("IRONCORE_SSO_REDIRECT_URI", "https://ironcore.internal/auth/callback")

    # ── Vault ─────────────────────────────────────────────────────────────────
    @property
    def vault_url(self) -> str:
        return os.environ.get("IRONCORE_VAULT_URL", "https://vault.bank.internal:8200")

    @property
    def vault_auth_method(self) -> str:
        return os.environ.get("IRONCORE_VAULT_AUTH_METHOD", "approle")

    # ── Telegram ──────────────────────────────────────────────────────────────
    @property
    def telegram_bot_token(self) -> str:
        return os.environ.get("IRONCORE_TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.environ.get("IRONCORE_TELEGRAM_CHAT_ID", "")

    # ── SMTP ──────────────────────────────────────────────────────────────────
    @property
    def smtp_host(self) -> str:
        return os.environ.get("IRONCORE_SMTP_HOST", "")

    @property
    def smtp_port(self) -> int:
        return int(os.environ.get("IRONCORE_SMTP_PORT", "587"))

    @property
    def smtp_from(self) -> str:
        return os.environ.get("IRONCORE_SMTP_FROM", "ironcore@internal")

    @property
    def smtp_to(self) -> str:
        return os.environ.get("IRONCORE_SMTP_TO", "")


# Global singleton — import this everywhere
cfg = IronCoreConfig()
