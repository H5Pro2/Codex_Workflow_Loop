"""Start or reopen the local Codex Workflow Loop application."""
import argparse
import json
from pathlib import Path
import urllib.request
import webbrowser
from app.service import Service, chat_id
from app.server import make_server

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:43821"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            running = json.load(response).get("app") == "workflow-loop"
        if running:
            if not args.no_browser:
                webbrowser.open(URL)
            return
    except (OSError, ValueError):
        pass
    storage = ROOT / "data" / "chats.json"
    old = ROOT / "chats.json"
    if old.exists() and not storage.exists():
        migrated = []
        for value in json.loads(old.read_text(encoding="utf-8")):
            try:
                identity = chat_id(value)
                if not any(row["id"] == identity for row in migrated):
                    migrated.append(dict(id=identity, label=""))
            except ValueError:
                continue
        storage.parent.mkdir(exist_ok=True)
        storage.write_text(json.dumps(migrated, indent=2), encoding="utf-8")
        old.unlink()
    service = Service(storage)
    server = make_server(service, ROOT / "web")
    if not args.no_browser:
        webbrowser.open(URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        server.server_close()


if __name__ == "__main__":
    main()
