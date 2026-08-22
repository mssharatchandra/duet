"""Capability-aware bridge to ASBL's internal product.

The language model may *request* an action, but only this boundary may confirm
that it happened.  The default is disabled.  Configure ASBL_ACTION_GATEWAY_URL
to POST idempotent action requests to the internal product.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ACTION_NAMES = ("send_brochure", "schedule_callback", "book_site_visit", "update_crm")
ACTION_STATUSES = ("accepted", "completed", "failed", "unavailable")
ALLOWED_ARGUMENTS = ("preferred_time", "channel", "notes", "project")


@dataclass(frozen=True)
class ActionRequest:
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    name: str
    status: str
    reference_id: str | None = None
    latency_ms: float = 0.0
    reason: str | None = None
    adapter: str = "remote"

    @property
    def spoken_confirmation(self) -> str:
        if self.adapter == "local-demo-ledger" and self.status == "accepted":
            return {
                "send_brochure": "I've recorded your brochure request in this demo for the ASBL team.",
                "schedule_callback": "I've recorded your callback preference in this demo for the ASBL team.",
                "book_site_visit": "I've recorded your site-visit request in this demo for the ASBL team.",
                "update_crm": "I've recorded that enquiry update in the local demo ledger.",
            }[self.name]
        if self.status == "completed":
            return {
                "send_brochure": "Done. ASBL's system has sent the official Broadway brochure.",
                "schedule_callback": "Done. Your advisor callback has been scheduled in ASBL's system.",
                "book_site_visit": "Done. Your site-visit request is confirmed in ASBL's system.",
                "update_crm": "Done. I have updated your enquiry in ASBL's system.",
            }[self.name]
        if self.status == "accepted":
            return {
                "send_brochure": "I have submitted the brochure request to ASBL's system.",
                "schedule_callback": "I have submitted your callback request to ASBL's system.",
                "book_site_visit": "I have submitted your site-visit request to ASBL's system.",
                "update_crm": "I have submitted the enquiry update to ASBL's system.",
            }[self.name]
        if self.status == "unavailable":
            return "That action is available through ASBL's internal product, but it is not connected to this demo yet."
        return "I couldn't complete that action just now. I have not marked it as done."


def parse_action_request(data) -> ActionRequest | None:
    if not isinstance(data, dict) or data.get("name") not in ACTION_NAMES:
        return None
    raw_arguments = data.get("arguments", {})
    if not isinstance(raw_arguments, dict):
        raw_arguments = {}
    arguments = {
        key: str(value).strip()[:240]
        for key, value in raw_arguments.items()
        if key in ALLOWED_ARGUMENTS and value is not None
    }
    return ActionRequest(name=data["name"], arguments=arguments)


def parse_action_requests(data) -> list[ActionRequest]:
    if not isinstance(data, list):
        return []
    parsed: list[ActionRequest] = []
    seen: set[str] = set()
    for item in data[:3]:
        action = parse_action_request(item)
        if action is not None and action.name not in seen:
            parsed.append(action)
            seen.add(action.name)
    return parsed


class ActionLayer:
    """Non-blocking, idempotent action executor.

    ``local`` records a genuine demo request in a local JSONL ledger and
    returns ``accepted``.  ``remote`` calls the internal product.  Neither
    mode equates acceptance with external completion.
    """

    def __init__(
        self,
        session_id: str,
        gateway_url: str | None = None,
        token: str | None = None,
        timeout_s: float = 4.0,
        mode: str | None = None,
        ledger_path: Path | None = None,
    ):
        self.session_id = session_id
        self.gateway_url = (gateway_url or os.environ.get("ASBL_ACTION_GATEWAY_URL", "")).rstrip("/")
        self.token = token or os.environ.get("ASBL_ACTION_GATEWAY_TOKEN", "")
        self.timeout_s = timeout_s
        configured_mode = mode or os.environ.get("ASBL_ACTION_MODE", "local")
        self.mode = "remote" if self.gateway_url else configured_mode
        self.ledger_path = ledger_path or Path(
            os.environ.get("ASBL_ACTION_LEDGER", ".local/asbl-actions.jsonl")
        )
        self.results: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def enabled(self) -> bool:
        return self.mode == "local" or bool(self.gateway_url)

    @property
    def capability_label(self) -> str:
        return "internal product" if self.mode == "remote" else "local demo ledger"

    def request(self, action: ActionRequest) -> str:
        with self._lock:
            self._sequence += 1
            action_id = f"{self.session_id}-{self._sequence}"
        if self.mode == "local":
            threading.Thread(target=self._record_local, args=(action_id, action), daemon=True).start()
            return action_id
        if not self.enabled:
            self.results.put(ActionResult(action.name, "unavailable", reference_id=action_id))
            return action_id
        threading.Thread(target=self._call, args=(action_id, action), daemon=True).start()
        return action_id

    def poll(self) -> ActionResult | None:
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def _record_local(self, action_id: str, action: ActionRequest) -> None:
        started = time.perf_counter()
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "action_id": action_id,
                "session_id": self.session_id,
                "name": action.name,
                "arguments": action.arguments,
                "status": "accepted",
                "recorded_at": time.time(),
                "adapter": "local-demo-ledger",
            }
            with self._lock, self.ledger_path.open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(record, sort_keys=True) + "\n")
            result = ActionResult(
                action.name,
                "accepted",
                reference_id=action_id,
                adapter="local-demo-ledger",
            )
        except Exception as error:  # noqa: BLE001 -- adapter failures must become fail-closed results
            result = ActionResult(
                action.name,
                "failed",
                reference_id=action_id,
                reason=f"{type(error).__name__}: {error}",
            )
        result.latency_ms = (time.perf_counter() - started) * 1000
        self.results.put(result)

    def _call(self, action_id: str, action: ActionRequest) -> None:
        started = time.perf_counter()
        try:
            payload = json.dumps(
                {
                    "action_id": action_id,
                    "session_id": self.session_id,
                    "name": action.name,
                    "arguments": action.arguments,
                }
            ).encode()
            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": action_id,
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            request = urllib.request.Request(self.gateway_url, data=payload, headers=headers)
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.load(response)
            status = body.get("status")
            if status not in {"accepted", "completed"}:
                status = "failed"
            result = ActionResult(
                name=action.name,
                status=status,
                reference_id=str(body.get("reference_id") or action_id),
                adapter="remote",
            )
        except Exception as error:  # noqa: BLE001 -- remote transport failures are external input
            result = ActionResult(
                name=action.name,
                status="failed",
                reference_id=action_id,
                reason=f"{type(error).__name__}: {error}",
            )
        result.latency_ms = (time.perf_counter() - started) * 1000
        self.results.put(result)
