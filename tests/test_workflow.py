import threading
import unittest
from app.workflow import Workflow, validate


def graph(limit=5):
    return {'nodes':[
        {'id':'s','kind':'start','prompt':'Hallo'},
        {'id':'a','kind':'chat','chat':'A'},
        {'id':'b','kind':'chat','chat':'B'},
        {'id':'c','kind':'chat','chat':'C'},
        {'id':'counter','kind':'counter','limit':limit}],
        'edges':[{'source':'s','target':'a'},{'source':'a','target':'b'},{'source':'b','target':'counter'},{'source':'counter','target':'a'}]}


class FakeService:
    def __init__(self):
        from unittest.mock import Mock
        self.debug=Mock()
        self.lock=threading.RLock()
        self.rows=[{'id':k} for k in 'ABC']
        self.monitored=[]
        self.sent=[]
        self.sources=[]
        self.turns={k:'old' for k in 'ABC'}
        self.bridge=self
        self.workflow=Workflow(self)
        self.workflow.graph=graph()

    def dispatch(self, identity, source, text, **kwargs):
        return self.send(identity,self.forward_text(source,text),source=source)

    def preflight(self, identity):
        pass

    def forward_text(self, source, text):
        return f'Nachricht von „{source}“\n\n{text}'

    def forwarded(self):
        pass

    def save(self):
        pass

    def command(self, action, identity):
        self.monitored.append(identity)

    def call(self, name, args):
        identity=args['targets'][0]['threadId']
        return {'polls':[{'thread':{'id':identity,'status':{'type':'idle'}},'latestTurn':{'id':self.turns[identity],'status':'completed'}}]}

    def send(self, identity, text, *, source):
        self.sent.append((identity,text))
        self.sources.append(source)
        self.turns[identity]='turn-'+str(len(self.sent))

    def workflow_answer(self, identity, turn):
        return 'Antwort '+turn


class WorkflowTests(unittest.TestCase):
    def test_five_rounds_and_disconnected_chat_untouched(self):
        service=FakeService()
        service.workflow.start()
        service.workflow.thread.join(3)
        self.assertFalse(service.workflow.thread.is_alive())
        self.assertEqual(service.monitored,['A','B'])
        self.assertEqual([x[0] for x in service.sent],['B','A']*5)
        self.assertEqual(service.sources,['A','B']*5)
        self.assertEqual(service.sent[0],('B','Nachricht von „A“\n\nAntwort old'))
        self.assertEqual(service.sent[1],('A','Nachricht von „B“\n\nAntwort turn-1'))
        self.assertEqual(service.workflow.run['counts'],{'counter':5})
        self.assertEqual(service.workflow.run['status'],'completed')

    def test_counter_between_chats_stops_at_its_position(self):
        service=FakeService()
        service.workflow.graph=graph(1)
        service.workflow.graph['edges']=[{'source':'s','target':'a'},{'source':'a','target':'counter'},{'source':'counter','target':'b'},{'source':'b','target':'a'}]
        service.workflow.start();service.workflow.thread.join(3)
        self.assertEqual([x[0] for x in service.sent],['B'])

    def test_stop_during_inflight_send_prevents_next_send(self):
        service=FakeService();entered=threading.Event();release=threading.Event()
        original=service.send
        def send(identity,text, *, source):
            original(identity,text,source=source);entered.set();release.wait(3)
        service.send=send
        service.workflow.start();self.assertTrue(entered.wait(2))
        service.workflow.stop();release.set();service.workflow.thread.join(3)
        self.assertEqual(len(service.sent),1)
        self.assertEqual(service.workflow.run['status'],'stopped')

    def test_unbounded_cycle_and_ambiguous_output_rejected(self):
        g=graph();g['edges']=[{'source':'s','target':'a'},{'source':'a','target':'b'},{'source':'b','target':'a'}]
        with self.assertRaises(ValueError):validate(g,set('ABC'),True)
        g=graph();g['edges'].append({'source':'a','target':'c'})
        with self.assertRaises(ValueError):validate(g,set('ABC'),True)

    def test_restart_does_not_automatically_send(self):
        service=FakeService()
        restored=Workflow(service,{'graph':graph(),'run':{'status':'running','counts':{'counter':2},'participants':['A','B']}})
        self.assertEqual(restored.run['status'],'stopped')
        self.assertEqual(restored.run['counts'],{'counter':2})
        self.assertEqual(service.sent,[])

    def test_missing_exact_answer_stops_instead_of_forwarding_old_text(self):
        service=FakeService()
        def missing(identity, turn):
            raise ValueError('Antwort nicht eindeutig')
        service.workflow_answer=missing
        service.workflow.start();service.workflow.thread.join(3)
        self.assertEqual(len(service.sent),0)
        self.assertEqual(service.workflow.run['status'],'error')

    def test_unfinished_source_does_not_send(self):
        service=FakeService()
        service.call=lambda *args: {'polls':[{'thread':{'id':'A','status':{'type':'idle'}},'latestTurn':{'id':'old','status':'failed'}}]}
        service.workflow.start();service.workflow.thread.join(3)
        self.assertEqual(service.sent,[])
        self.assertEqual(service.workflow.run['status'],'error')

    def test_start_needs_no_prompt_and_discards_legacy_prompt(self):
        g=graph();g['nodes'][0].pop('prompt')
        clean,*_=validate(g,set('ABC'),True)
        self.assertNotIn('prompt',clean['nodes'][0])

    def test_running_allows_only_position_changes(self):
        import copy
        service=FakeService()
        service.workflow.run['status']='running'
        updated=copy.deepcopy(service.workflow.graph)
        updated['nodes'][1]['x']=240
        service.workflow.save_graph(updated)
        self.assertEqual(service.workflow.graph['nodes'][1]['x'],240)
        updated['nodes'][-1]['limit']=99
        with self.assertRaises(ValueError):service.workflow.save_graph(updated)

    def test_preflight_failure_preserves_counter_and_sends_nothing(self):
        service=FakeService()
        service.workflow.run.update(status='completed',counts={'counter':5})
        def fail(identity): raise ValueError('Disconnected')
        service.preflight=fail
        with self.assertRaises(ValueError):service.workflow.start()
        self.assertEqual(service.workflow.run['counts'],{'counter':5})
        self.assertEqual(service.sent,[])

    def test_counter_change_resets_finished_run_but_position_keeps_count(self):
        import copy
        service=FakeService()
        service.workflow.graph=graph(2)
        service.workflow.run.update(status='completed',counts={'counter':2})
        moved=copy.deepcopy(service.workflow.graph)
        moved['nodes'][0]['x']=200
        service.workflow.save_graph(moved)
        self.assertEqual(service.workflow.run['counts'],{'counter':2})
        moved['nodes'][-1]['limit']=5
        service.workflow.save_graph(moved)
        self.assertEqual(service.workflow.run['counts'],{})
        self.assertEqual(service.workflow.run['status'],'idle')

    def test_counter_reset_rolls_back_when_save_fails(self):
        service=FakeService()
        service.workflow.graph=graph(2)
        service.workflow.run.update(status='completed',counts={'counter':2})
        def fail():raise OSError('Disk unavailable')
        service.save=fail
        with self.assertRaises(OSError):service.workflow.save_graph(graph(5))
        self.assertEqual(service.workflow.run['counts'],{'counter':2})
        self.assertEqual(service.workflow.graph['nodes'][-1]['limit'],2)

    def test_direct_side_message_stops_loop_before_next_dispatch(self):
        service=FakeService()
        original=service.send
        def side_send(identity,text, *, source):
            original(identity,text,source=source)
            service.turns[source]='unexpected-direct-message'
        service.send=side_send
        service.workflow.start();service.workflow.thread.join(3)
        self.assertEqual(len(service.sent),1)
        self.assertEqual(service.workflow.run['status'],'error')
        self.assertIn('außerhalb des Loops',service.workflow.run['message'])
        self.assertEqual(service.workflow.run['counts'],{})
