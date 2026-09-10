import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app.service import Service, chat_id
from app.server import make_server

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


def event(kind, identity):
    return json.dumps(dict(type="event_msg", timestamp=datetime.now(timezone.utc).isoformat(), payload=dict(type=kind, turn_id=identity))) + "\n"


class ServiceTests(unittest.TestCase):
    def test_reorder_persists_and_rejects_missing_chats(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Path(directory)/'chats.json', Path(directory))
            try:
                service.command('add', A);service.command('add', B)
                service.command('reorder', [B,A])
                self.assertEqual([r['id'] for r in service.rows], [B,A])
                self.assertEqual([r['id'] for r in json.loads(service.storage.read_text())['chats']], [B,A])
                with self.assertRaises(ValueError):service.command('reorder', [A,A])
                self.assertEqual([r['id'] for r in service.rows], [B,A])
            finally:
                service.close()

    def test_reassign_preserves_graph_and_persists_new_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Path(directory)/'chats.json', Path(directory))
            service.command('add', A)
            service.workflow.graph={'nodes':[{'id':'node','kind':'chat','chat':A}], 'edges':[]}
            try:
                with patch('app.service.read_titles', return_value={B:'Neuer Chat'}):
                    service.command('reassign', A, 'codex://threads/'+B)
                self.assertEqual(service.rows[0]['id'], B)
                self.assertEqual(service.rows[0]['title'], 'Neuer Chat')
                self.assertEqual(service.workflow.graph['nodes'][0]['chat'], B)
                self.assertEqual(json.loads(service.storage.read_text())['chats'][0]['id'], B)
                service.command('add', A)
                with self.assertRaises(ValueError):service.command('reassign', B, A)
                service.workflow.run['status']='running'
                with self.assertRaises(ValueError):service.command('reassign', B, A)
            finally:
                service.close()

    def test_send_uses_copied_text_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / "chats.json", Path(directory))
            service.transfers["test-token"] = dict(source=A, text="Die kopierte Antwort", created=time.monotonic())
            try:
                with patch.object(service, "check_target") as check, patch.object(service.bridge, "send", return_value={"threadId": B}) as send:
                    result = service.send_transfer("test-token", B)
                    self.assertEqual(result["confirmation"], {"threadId": B})
                    self.assertEqual(service.send_transfer("test-token", B), result)
                    send.assert_called_once_with(B, "Die kopierte Antwort")
                    check.assert_called_once_with(A, B)
            finally:
                service.close()

    def test_uncertain_send_is_not_retried_and_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / "chats.json", Path(directory))
            service.transfers["test-token"] = dict(source=A, text="Test", created=time.monotonic())
            try:
                with self.assertRaises(ValueError):
                    service.send_transfer("test-token", A)
                with patch.object(service, "check_target"), patch.object(service.bridge, "send", side_effect=RuntimeError("Uncertain")) as send:
                    with self.assertRaises(RuntimeError):
                        service.send_transfer("test-token", B)
                    with self.assertRaises(ValueError):
                        service.send_transfer("test-token", B)
                    self.assertEqual(send.call_count, 1)
            finally:
                service.close()

    def test_deeplink_and_validation(self):
        self.assertEqual(chat_id("codex://threads/" + A), A)
        for value in ("", "invalid", A + B):
            with self.assertRaises(ValueError):
                chat_id(value)

    def test_independent_workers_and_durable_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"rollout-{identity}.jsonl" for identity in (A, B)]
            for path in paths:
                path.write_text(event("task_started", "running"))
            service = Service(root / "chats.json", root)
            def wait_for(check):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if check():
                        return
                    time.sleep(.03)
                self.fail("Worker did not reach expected state")
            try:
                for identity in (A, B):
                    service.command("add", identity, "Test")
                    service.command("start", identity)
                wait_for(lambda: all(r["state"] == "working" for r in service.snapshot()["chats"]))
                service.command("pause", A)
                self.assertFalse(service.snapshot()["chats"][0]["active"])
                service.command("start", A)
                wait_for(lambda: service.snapshot()["chats"][0]["state"] == "working")
                with paths[0].open("a") as stream:
                    stream.write(event("task_complete", "running"))
                wait_for(lambda: service.snapshot()["chats"][0]["count"] == 1)
                self.assertEqual(service.snapshot()["chats"][1]["state"], "working")
                with paths[1].open("a") as stream:
                    stream.write(event("turn_aborted", "running"))
                wait_for(lambda: service.snapshot()["chats"][1]["state"] == "error")
                service.command("pause", B)
                service.command("start", B)
                wait_for(lambda: service.snapshot()["chats"][1]["state"] == "waiting")
                self.assertEqual(service.snapshot()["chats"][1]["count"], 0)
                service.command("pause", A)
                service.command("sound", True)
                with patch.object(Service, "watch"):
                    restored = Service(root / "chats.json", root)
                try:
                    snapshot = restored.snapshot()
                    self.assertFalse(snapshot["chats"][0]["active"])
                    self.assertTrue(snapshot["chats"][1]["active"])
                    self.assertEqual(snapshot["chats"][0]["count"], 1)
                    self.assertEqual(len(snapshot["events"]), 1)
                    self.assertTrue(snapshot["sound"])
                finally:
                    restored.close()
                with self.assertRaises(ValueError):
                    service.command("add", A)
            finally:
                service.close()

    def test_http_lifecycle_and_origin_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / "chats.json", Path(directory))
            server = make_server(service, Path(__file__).resolve().parents[1] / "web", 0)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def post(body, origin=base):
                return urlopen(Request(base + "/api/command", data=json.dumps(body).encode(), headers={"Origin": origin, "X-Workflow-Loop": "1", "Content-Type": "application/json"}), timeout=3)
            try:
                with urlopen(base) as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(HTTPError) as error:
                    post(dict(action="add", id=A), "https://example.com")
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                with post(dict(action="add", id=A)) as response:
                    self.assertEqual(len(json.load(response)["chats"]), 1)
                with urlopen(base + "/api/state") as response:
                    self.assertEqual(json.load(response)["chats"][0]["id"], A)
                with post(dict(action="remove", id=A)) as response:
                    self.assertEqual(json.load(response)["chats"], [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                service.close()
