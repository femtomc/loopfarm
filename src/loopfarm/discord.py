from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .util import env_flag, env_value


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any | None = None,
    timeout: float = 20.0,
) -> tuple[int, Any]:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "loopfarm/1.0")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else None
        except Exception:
            payload = raw
        return e.code, payload
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def _truncate(s: str, n: int) -> str:
    return s[:n]


@dataclass
class DiscordClient:
    webhook: str | None
    bot_token: str | None
    debug: bool = False

    _bot_user_id: str | None = None

    @classmethod
    def from_env(cls) -> "DiscordClient":
        return cls(
            webhook=env_value("LOOPFARM_DISCORD_WEBHOOK") or None,
            bot_token=env_value("LOOPFARM_DISCORD_BOT_TOKEN") or None,
            debug=env_flag("LOOPFARM_DISCORD_DEBUG"),
        )

    def post(self, content: str, *, thread_id: str | None) -> bool:
        if not self.webhook or not thread_id:
            return False

        content = _truncate(content, 2000)
        url = f"{self.webhook}?wait=true&thread_id={thread_id}"
        for attempt in range(2):
            status, payload = _http_json(
                "POST",
                url,
                body={"content": content, "allowed_mentions": {"parse": []}},
            )
            if status == 429 and isinstance(payload, dict):
                retry_after = payload.get("retry_after", 5)
                if self.debug:
                    print(
                        f"[discord] Rate limited, retry after {retry_after}s",
                        file=sys.stderr,
                    )
                time.sleep(float(retry_after))
                continue
            if status // 100 == 2:
                return True
            if self.debug:
                print(f"[discord] POST failed: {status} - {payload!r}", file=sys.stderr)
            return False
        if self.debug:
            print("[discord] POST failed after retry", file=sys.stderr)
        return False

    def create_thread(self, thread_name: str, content: str) -> str | None:
        if not self.webhook:
            return None

        thread_name = _truncate(thread_name, 100)
        content = _truncate(content, 2000)
        for attempt in range(2):
            status, payload = _http_json(
                "POST",
                f"{self.webhook}?wait=true",
                body={
                    "thread_name": thread_name,
                    "content": content,
                    "allowed_mentions": {"parse": []},
                },
            )
            if status == 429 and isinstance(payload, dict):
                retry_after = payload.get("retry_after", 5)
                if self.debug:
                    print(
                        f"[discord] Rate limited, retry after {retry_after}s",
                        file=sys.stderr,
                    )
                time.sleep(float(retry_after))
                continue
            if status // 100 == 2 and isinstance(payload, dict):
                return payload.get("channel_id") or None
            if self.debug:
                print(
                    f"[discord] Thread creation failed: {status} - {payload!r}",
                    file=sys.stderr,
                )
            return None
        if self.debug:
            print("[discord] Thread creation failed after retry", file=sys.stderr)
        return None

    def _bot_headers(self) -> dict[str, str] | None:
        if not self.bot_token:
            return None
        return {"Authorization": f"Bot {self.bot_token}"}

    def get_bot_user_id(self) -> str | None:
        if self._bot_user_id is not None:
            return self._bot_user_id
        if not self.bot_token:
            return None
        status, payload = _http_json(
            "GET",
            "https://discord.com/api/v10/users/@me",
            headers=self._bot_headers(),
        )
        if status // 100 != 2 or not isinstance(payload, dict):
            return None
        bot_id = payload.get("id")
        self._bot_user_id = bot_id
        return bot_id

    def read_messages(self, thread_id: str, *, after_id: str | None) -> list[dict[str, Any]]:
        if not self.bot_token or not thread_id:
            return []

        url = f"https://discord.com/api/v10/channels/{thread_id}/messages?limit=100"
        if after_id:
            url += f"&after={after_id}"

        status, payload = _http_json("GET", url, headers=self._bot_headers())

        if status == 429 and isinstance(payload, dict):
            retry_after = payload.get("retry_after", 5)
            if self.debug:
                print(f"[discord] Rate limited, retry after {retry_after}s", file=sys.stderr)
            time.sleep(float(retry_after))
            return self.read_messages(thread_id, after_id=after_id)

        if status // 100 != 2 or not isinstance(payload, list):
            if self.debug:
                print(f"[discord] Read failed: {status} - {payload!r}", file=sys.stderr)
            return []

        return payload
