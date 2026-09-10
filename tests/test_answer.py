import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from app.service import Service
from app.workflow import EmptyAnswer

class AnswerTests(unittest.TestCase):
    def check_answer(self, records, expected=None, error=None, delayed=False):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory)/'chats.json', Path(directory))
            path = Path(directory)/'rollout.jsonl'
            def write(text):
                path.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':records,'last_agent_message':text}})+'\n', encoding='utf-8')
            write('' if delayed else expected)
            service.workflow.stop_event = Mock()
            service.workflow.stop_event.is_set.return_value = False
            def wait(_):
                if delayed: write(expected)
                return False
            service.workflow.stop_event.wait.side_effect = wait
            with patch('app.service.read_rollout',return_value=path):
                if error:
                    with self.assertRaises(error): service.workflow_answer('chat','new')
                else:
                    self.assertEqual(service.workflow_answer('chat','new'),expected)
            service.close()

    def test_empty_completed_turn_is_explicit_stop(self):
        self.check_answer('new', error=EmptyAnswer)

    def test_old_answer_is_never_used(self):
        self.check_answer('old', expected='Old answer', error=ValueError)

    def test_delayed_answer_is_read_on_retry(self):
        self.check_answer('new', expected='New answer', delayed=True)
