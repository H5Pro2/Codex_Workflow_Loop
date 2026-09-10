import json
from pathlib import Path
import tempfile
import unittest
from app.monitor import Tail


class TailTests(unittest.TestCase):
    def test_baseline_completion_duplicate_and_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            def event(kind, turn):
                return (json.dumps({"type": "event_msg", "payload": {"type": kind, "turn_id": turn}}) + "\n").encode()
            path.write_bytes(event("task_complete", "old"))
            tail = Tail()
            self.assertEqual(tail.poll(path), [])
            with path.open("ab") as stream:
                stream.write(event("task_started", "new"))
                stream.write(event("task_complete", "new")[:-1])
            self.assertEqual(tail.poll(path), [("task_started", "")])
            with path.open("ab") as stream:
                stream.write(b"\n" + event("task_complete", "new"))
            self.assertEqual(tail.poll(path), [("task_complete", "")])
            self.assertEqual(tail.poll(path), [])

    def test_failure_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(b"")
            tail = Tail()
            tail.poll(path)
            path.write_text(json.dumps({"type": "event_msg", "payload": {"type": "turn_aborted", "turn_id": "a"}}) + "\n")
            self.assertEqual(tail.poll(path), [("turn_aborted", "")])


if __name__ == "__main__":
    unittest.main()
