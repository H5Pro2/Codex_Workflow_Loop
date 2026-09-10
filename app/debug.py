"""Bounded, persistent diagnostics without message bodies or bridge credentials."""
import copy
import hashlib
import json
import threading
from datetime import datetime, timezone
from uuid import uuid4


def fingerprint(text):
    data=text.encode('utf-8')
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class DebugLog:
    def __init__(self, path, limit=1000):
        self.path=path
        self.limit=limit
        self.lock=threading.RLock()
        self.entries=[]
        self.error=None
        try:
            if path.exists():
                entries=json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(entries,list):raise ValueError('Invalid debug data')
                self.entries=entries[-limit:]
        except (OSError,ValueError):
            self.error='Vorhandenes Debug-Protokoll konnte nicht gelesen werden.'

    def snapshot(self):
        with self.lock:
            return dict(entries=copy.deepcopy(self.entries),error=self.error,limit=self.limit)

    def persist(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.entries,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(self.path)

    def record(self, event, **fields):
        with self.lock:
            self.entries.append(dict(id=str(uuid4()),time=datetime.now(timezone.utc).isoformat(),event=event,**fields))
            self.entries=self.entries[-self.limit:]
            try:
                self.persist()
                self.error=None
            except OSError:
                self.error='Debug-Protokoll nur im Speicher; Speicherung fehlgeschlagen.'

    def clear(self):
        with self.lock:
            previous=self.entries
            self.entries=[]
            try:self.persist()
            except OSError:
                self.entries=previous
                raise
            self.error=None
