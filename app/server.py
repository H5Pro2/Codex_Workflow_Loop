"""Loopback-only HTTP interface, with same-origin mutation protection."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from .bridge import BridgeError


def make_server(service, web, port=43821):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            data = json.dumps(body, ensure_ascii=False).encode() if not isinstance(body, bytes) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {"error": "Ungültiger Host"})
            if self.path == "/api/debug":
                return self.reply(200, service.debug.snapshot())
            if self.path == "/api/state":
                return self.reply(200, service.snapshot())
            if self.path == "/api/health":
                return self.reply(200, {"app": "workflow-loop", "version": 2})
            files = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"), "/app.js": ("app.js", "text/javascript"), '/debug.js':('debug.js','text/javascript'), '/workflow.js':('workflow.js','text/javascript'), '/workflow.css':('workflow.css','text/css')}
            if self.path not in files:
                return self.reply(404, {"error": "Nicht gefunden"})
            name, mime = files[self.path]
            self.reply(200, (web / name).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            if not self.allowed() or self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}" or self.headers.get("X-Workflow-Loop") != "1":
                return self.reply(403, {"error": "Zugriff nur aus der lokalen Oberfläche erlaubt"})
            if self.path not in ("/api/command", "/api/shutdown", "/api/copy", "/api/target", "/api/send", '/api/workflow'):
                return self.reply(404, {"error": "Nicht gefunden"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (65536 if self.path == '/api/workflow' else 8192):
                    raise ValueError("Ungültige Anfragegröße")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Ungültige Anfrage")
                if self.path == '/api/workflow':
                    action = body.get('action')
                    if action == 'save':
                        service.workflow.save_graph(body.get('graph'))
                    elif action == 'start':
                        service.workflow.start()
                    elif action == 'stop':
                        service.workflow.stop()
                    else:
                        raise ValueError('Unbekannte Workflow-Aktion.')
                    self.reply(200, service.snapshot())
                    return
                if self.path == "/api/copy":
                    self.reply(200, service.copy_answer(body.get("id", "")))
                    return
                if self.path == "/api/send":
                    self.reply(200, service.send_transfer(body.get("token"), body.get("target")))
                    return
                if self.path == "/api/target":
                    self.reply(200, service.check_target(body.get("source", ""), body.get("target", "")))
                    return
                if self.path == "/api/shutdown":
                    service.close()
                    self.reply(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                service.command(body.get("action"), body.get("id", ""), body.get("label", ""))
                self.reply(200, service.snapshot())
            except (ValueError, TypeError) as error:
                self.reply(400, {"error": str(error)})
            except OSError:
                self.reply(500, {"error": "Lokale Daten konnten nicht gespeichert werden."})
            except BridgeError as error:
                self.reply(502, {"error": str(error)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
