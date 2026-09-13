from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from ironcore.tui.i18n import i18n, normalize_language

API_BASE = "http://127.0.0.1:8000"


def push_language_to_backend(code: str, source: str = "tui") -> None:
    payload = json.dumps({
        "language": normalize_language(code),
        "source": source,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE}/api/i18n/state",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=1.5):
            return
    except Exception:
        return


class TUILanguageSyncClient:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self, app: Any) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, args=(app,), daemon=True)
        self._thread.start()

    def _run(self, app: Any) -> None:
        # Keep this lightweight and fail-safe: if backend stream is unavailable,
        # just skip syncing and let local language selection drive the flow.
        try:
            req = urllib.request.Request(
                f"{API_BASE}/api/i18n/state",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
                incoming = normalize_language(str(body.get("language", "en")))
                if incoming and incoming != i18n.current_lang:
                    i18n.load_language(incoming)
                    try:
                        app.call_from_thread(lambda: app.notify(f"Language synced: {incoming}"))
                    except Exception:
                        pass
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            return
