import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.debug import DebugLog, fingerprint
from app.service import Service

class DebugTests(unittest.TestCase):
    def test_bounded_persistence_clear_and_hash_without_body(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'debug.json';log=DebugLog(path,limit=2)
            for i in range(3):log.record('sent',number=i,answer=fingerprint('Private message'))
            self.assertNotIn('Private message',path.read_text())
            restored=DebugLog(path,limit=2)
            self.assertEqual([e['number'] for e in restored.snapshot()['entries']],[1,2])
            restored.clear();self.assertEqual(DebugLog(path).snapshot()['entries'],[])

    def test_storage_failure_keeps_memory_and_reports_error(self):
        with tempfile.TemporaryDirectory() as folder:
            log=DebugLog(Path(folder)/'debug.json')
            with patch.object(log,'persist',side_effect=OSError('disk')):
                log.record('requested')
                self.assertTrue(log.snapshot()['error'])
                with self.assertRaises(OSError):log.clear()
            self.assertEqual(len(log.snapshot()['entries']),1)

    def test_uncertain_send_never_logs_confirmation_or_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder)/'chats.json',Path(folder))
            try:
                with patch.object(service,'forward_text',return_value='wrapped'),patch.object(service.bridge,'send',side_effect=RuntimeError('uncertain')) as send:
                    with self.assertRaises(RuntimeError):service.dispatch('target','source','private',mode='loop',run='run1')
                    send.assert_called_once()
                entries=[e for e in service.debug.snapshot()['entries'] if e['event'].startswith('dispatch_')]
                self.assertEqual([e['event'] for e in entries],['dispatch_requested','dispatch_unconfirmed'])
                self.assertEqual(entries[0]['delivery'],entries[1]['delivery'])
                self.assertNotIn('private',json.dumps(entries))
            finally:service.close()
