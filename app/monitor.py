"""Incremental, read-only Codex session event reader."""
import json
from datetime import datetime, timezone


class Tail:
    def __init__(self):
        self.offset = 0
        self.pending = b""
        self.seen = set()
        self.initialized = False
        self.last_kind = None
        self.last_turn = None
        self.final_text = ""
        self.completed_text = ""
        self.last_activity = None

    def activity_recent(self, now=None):
        if self.last_activity is None:
            return False
        return 0 <= ((now or datetime.now(timezone.utc)) - self.last_activity).total_seconds() <= 120

    def allows_paste(self):
        return self.last_kind in ("task_complete", "turn_aborted", "task_failed") or (
            self.last_kind == "task_started" and not self.activity_recent()
        )

    def poll(self, path):
        notices = []
        with path.open("rb") as stream:
            if path.stat().st_size < self.offset:
                self.offset = 0
                self.pending = b""
            stream.seek(self.offset)
            data = self.pending + stream.read()
            self.offset = stream.tell()
        lines = data.split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            try:
                entry = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            payload = entry.get("payload", {})
            if entry.get("type") in ("event_msg", "response_item", "turn_context") and payload.get("type") != "thread_settings_applied":
                try:
                    stamp = datetime.fromisoformat(entry.get("timestamp", "").replace("Z", "+00:00"))
                    if stamp.tzinfo is not None:
                        self.last_activity = stamp
                except (ValueError, TypeError):
                    pass
            if entry.get("type") == "response_item" and payload.get("role") == "assistant" and payload.get("phase") == "final_answer":
                self.final_text = "".join(item.get("text", "") for item in payload.get("content", []) if item.get("type") in ("output_text", "text"))
            if entry.get("type") != "event_msg":
                continue
            payload = entry.get("payload", {})
            kind = payload.get("type")
            if kind not in ("task_complete", "task_started", "turn_aborted", "task_failed"):
                continue
            identity = (kind, payload.get("turn_id"), entry.get("timestamp"))
            if identity in self.seen:
                continue
            self.seen.add(identity)
            self.last_kind = kind
            self.last_turn = payload.get('turn_id')
            if kind == "task_started":
                self.final_text = ""
                self.completed_text = ""
            elif kind == "task_complete":
                text = payload.get("last_agent_message")
                self.completed_text = text if isinstance(text, str) and text.strip() else self.final_text
            else:
                self.completed_text = ""
            if self.initialized:
                notices.append((kind, entry.get("timestamp", "")))
        self.initialized = True
        return notices

