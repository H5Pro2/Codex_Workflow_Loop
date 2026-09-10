import unittest
from unittest.mock import patch
from app.bridge import Bridge, BridgeError


class DesktopBridgeTests(unittest.TestCase):
    def test_send_uses_real_app_tool_after_live_check(self):
        bridge = Bridge()
        idle = {"polls": [{"thread": {"id": "target", "status": {"type": "idle"}}, "latestTurn": {"status": "completed"}}]}
        with patch.object(bridge, "call", side_effect=[idle, {"threadId": "target"}]) as call:
            self.assertEqual(bridge.send("target", "exact message", source="analyst"), {"threadId": "target"})
            self.assertEqual(call.call_args_list[1].kwargs, {"source":"analyst"})
            self.assertEqual(call.call_args_list[1].args, ("send_message_to_thread", {"threadId": "target", "prompt": "exact message"}))

    def test_active_target_never_receives_message(self):
        bridge = Bridge()
        active = {"polls": [{"thread": {"id": "target", "status": {"type": "active"}}}]}
        with patch.object(bridge, "call", return_value=active) as call:
            with self.assertRaises(BridgeError):
                bridge.send("target", "message", source="analyst")
            self.assertEqual(call.call_count, 1)

    def test_missing_runtime_uses_current_codex_environment(self):
        import tempfile
        from pathlib import Path
        from app.bridge import resolve_runtime
        with tempfile.TemporaryDirectory() as directory:
            node=Path(directory)/'node.exe';node.touch()
            module=Path(directory)/'server.mjs';module.touch()
            with patch.dict('os.environ', {'CODEX_MCP_NODE_PATH':str(node)}):
                config=resolve_runtime(dict(node=str(Path(directory)/'missing.exe'),module=str(module),pipe='local',thread='context'))
            self.assertEqual(config['node'],str(node))

    def test_send_context_is_per_request_and_does_not_change_default(self):
        bridge=Bridge();bridge.context='development-chat'
        response={'content':[{'type':'text','text':'{"threadId":"target"}'}]}
        with patch.object(bridge,'ensure'), patch.object(bridge,'request',return_value=response) as request:
            bridge.call('send_message_to_thread',{'threadId':'target','prompt':'exact'},source='analyst')
            self.assertEqual(request.call_args.args[1]['_meta'],{'threadId':'analyst'})
            bridge.call('send_message_to_thread',{'threadId':'analyst','prompt':'reply'},source='researcher')
            self.assertEqual(request.call_args.args[1]['_meta'],{'threadId':'researcher'})
        self.assertEqual(bridge.context,'development-chat')
