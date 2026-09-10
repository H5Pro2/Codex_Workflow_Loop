"""A bounded, single-path workflow. Graph editing never sends messages."""
import copy
import math
import threading
import time
from uuid import uuid4


def validate(graph, known, runnable=False):
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list):
        raise ValueError('Ungültiger Verbindungsplan.')
    if len(graph['nodes']) > 64 or len(graph['edges']) > 64:
        raise ValueError('Maximal 64 Bausteine und Verbindungen erlaubt.')
    nodes, edges, chats = {}, {}, set()
    for raw in graph['nodes']:
        if not isinstance(raw, dict):
            raise ValueError('Ungültiger Baustein.')
        key, kind = raw.get('id'), raw.get('kind')
        if not isinstance(key, str) or not key or key in nodes or kind not in ('start','chat','counter'):
            raise ValueError('Ungültiger oder doppelter Baustein.')
        node = dict(id=key, kind=kind)
        for axis in ('x','y'):
            value = raw.get(axis, 40)
            if not isinstance(value, (int,float)) or not math.isfinite(value):
                raise ValueError('Ungültige Position.')
            node[axis] = max(0, min(3000, value))
        if kind == 'chat':
            identity = raw.get('chat')
            if identity not in known or identity in chats:
                raise ValueError('Chat fehlt in der Übersicht oder wurde doppelt eingefügt.')
            chats.add(identity)
            node['chat'] = identity
        elif kind == 'counter':
            limit = raw.get('limit', 5)
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError('Counter: 1 bis 1000 Durchläufe eingeben.')
            node['limit'] = limit
        nodes[key] = node
    starts = [n for n in nodes.values() if n['kind']=='start']
    if len(starts) > 1:
        raise ValueError('Nur ein Start-Baustein ist erlaubt.')
    for edge in graph['edges']:
        if not isinstance(edge, dict):
            raise ValueError('Ungültige Verbindung.')
        source, target = edge.get('source'), edge.get('target')
        if source not in nodes or target not in nodes or source == target or nodes[target]['kind']=='start':
            raise ValueError('Ungültige Verbindung.')
        if source in edges:
            raise ValueError('Jeder Ausgang darf genau ein Ziel haben. Alte Verbindung zuerst entfernen.')
        edges[source] = target
    path = []
    if starts:
        current = starts[0]['id']
        while current not in path:
            path.append(current)
            if current not in edges:
                break
            current = edges[current]
        else:
            if not any(nodes[k]['kind']=='counter' for k in path[path.index(current):]):
                raise ValueError('Jede erreichbare Schleife braucht einen Counter.')
    if runnable:
        if len(starts)!=1:
            raise ValueError('Einen Start-Baustein anlegen.')
        if starts[0]['id'] not in edges or not any(nodes[k]['kind']=='chat' for k in path):
            raise ValueError('Den Start mit mindestens einem Chat verbinden.')
        # A counter-only cycle would consume rounds without any chat work.
        if current in path and current in edges and not any(nodes[k]['kind']=='chat' for k in path[path.index(current):]):
            raise ValueError('Eine Schleife muss mindestens einen Chat enthalten.')
    clean = dict(nodes=list(nodes.values()), edges=[dict(source=s,target=t) for s,t in edges.items()])
    return clean, nodes, edges, path


class EmptyAnswer(ValueError):
    """The exact completed turn contains no text to forward."""


class Workflow:
    def __init__(self, service, saved=None):
        self.service = service
        self.lock = threading.RLock()
        self.graph = (saved or {}).get('graph', {'nodes':[], 'edges':[]})
        self.run = (saved or {}).get('run', dict(status='idle', message='Start mit dem Quellchat verbinden.', counts={}, node=None, participants=[]))
        if self.run.get('status') in ('running','stopping'):
            self.run.update(status='stopped', message='Dienst neu gestartet. Kein automatischer Neuversand; Start beginnt einen neuen Lauf.')
        if self.run.get('status') == 'idle':
            self.run['message'] = 'Start mit dem Quellchat verbinden.'
        self.stop_event = threading.Event()
        self.thread = None

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(graph=self.graph, run=self.run))

    def persist(self):
        with self.service.lock:
            self.service.save()

    def busy(self):
        return self.run.get('status') in ('running','stopping')

    def contains(self, identity):
        return self.busy() and identity in self.run.get('participants',[])

    def update(self, **fields):
        with self.lock:
            self.run.update(fields)
        self.persist()
        if any(k in fields for k in ('status','counts')):
            self.service.debug.record('workflow_state',run=self.run.get('id'),status=self.run.get('status'),message=self.run.get('message'),counts=self.run.get('counts'),node=self.run.get('node'))

    def save_graph(self, graph):
        clean, _, _, _ = validate(graph, {r['id'] for r in self.service.rows})
        with self.lock:
            if self.busy():
                def structure(value):
                    return dict(nodes=sorted([{k:v for k,v in n.items() if k not in ('x','y')} for n in value['nodes']], key=lambda n:n['id']), edges=sorted(value['edges'], key=lambda e:(e['source'],e['target'])))
                current, _, _, _ = validate(self.graph, {r['id'] for r in self.service.rows})
                if structure(clean) != structure(current):
                    raise ValueError('Während des Ablaufs dürfen nur Positionen verändert werden.')
            previous = self.graph
            previous_run = copy.deepcopy(self.run)
            limits = lambda plan: {n['id']:n.get('limit',5) for n in plan['nodes'] if n['kind']=='counter'}
            if limits(previous) != limits(clean):
                self.run = dict(status='idle', message='Counter geändert · bereit für einen neuen Ablauf.', counts={}, node=None, participants=[])
            self.graph = clean
        try:
            self.persist()
        except OSError:
            with self.lock:
                self.graph = previous
                self.run = previous_run
            raise

    def start(self):
        with self.lock:
            if self.busy() or (self.thread and self.thread.is_alive()):
                raise ValueError('Der Ablauf läuft bereits.')
            _, initial_nodes, _, initial_path = validate(self.graph, {r['id'] for r in self.service.rows}, True)
            source = next(initial_nodes[k]['chat'] for k in initial_path if initial_nodes[k]['kind']=='chat')
        self.service.debug.record('preflight_requested',source=source)
        try:
            self.service.bridge.preflight(source)
        except Exception as error:
            self.service.debug.record('preflight_failed',source=source,error_type=type(error).__name__,message='App-Verbindung nicht bestätigt; Zähler bleibt erhalten.')
            raise
        self.service.debug.record('preflight_confirmed',source=source)
        with self.lock:
            if self.busy() or (self.thread and self.thread.is_alive()):
                raise ValueError('Der Ablauf läuft bereits oder wird noch gestoppt.')
            _, nodes, edges, path = validate(self.graph, {r['id'] for r in self.service.rows}, True)
            participants = [nodes[k]['chat'] for k in path if nodes[k]['kind']=='chat']
            self.stop_event = threading.Event()
            self.run = dict(id=str(uuid4()),status='running', message='Ablauf wird vorbereitet …', node=path[0], counts={}, participants=participants)
            self.thread = threading.Thread(target=self.execute, args=(nodes,edges,path[0],self.stop_event), daemon=True)
        try:
            self.persist()
        except OSError:
            self.run.update(status='error', message='Laufzustand konnte nicht gespeichert werden. Kein Chat gestartet.')
            self.thread = None
            raise
        self.service.debug.record('workflow_started',run=self.run['id'],participants=participants)
        self.thread.start()

    def stop(self):
        if self.busy():
            self.service.debug.record('stop_requested',run=self.run.get('id'))
        with self.lock:
            self.stop_event.set()
            if self.busy():
                self.run.update(status='stopping', message='Stopp angefordert. Bereits begonnene Übergabe darf abschließen; keine nächste Übergabe.')
        self.persist()

    def poll(self, identity):
        result = self.service.bridge.call('wait_threads', {'targets':[{'threadId':identity}],'timeoutMs':0})
        entries = result.get('polls', [])
        if not entries or entries[0].get('thread',{}).get('id') != identity:
            raise ValueError('Codex bestätigt den Zielchat nicht.')
        return entries[0]

    def idle(self, identity, stop):
        while not stop.is_set():
            entry = self.poll(identity)
            flags = entry.get('thread',{}).get('status',{}).get('activeFlags',[])
            if flags:
                raise ValueError('Codex benötigt Aufmerksamkeit. Bitte Zielchat prüfen.')
            if entry.get('thread',{}).get('status',{}).get('type') != 'active' and (entry.get('latestTurn') or {}).get('status') != 'inProgress':
                return entry
            self.update(message='Zielchat arbeitet noch · warte …')
            stop.wait(1)
        return None

    def check_other_chats(self, active):
        for identity, previous in self.observed_turns.items():
            if identity == active:
                continue
            entry = self.poll(identity)
            turn = entry.get('latestTurn') or {}
            if turn.get('id') != previous or turn.get('status') == 'inProgress' or entry.get('thread',{}).get('status',{}).get('type') == 'active':
                self.service.debug.record('unexpected_turn',run=self.run.get('id'),target=identity,expected_turn=previous,observed_turn=turn.get('id'))
                raise ValueError('Zusätzlicher Auftrag außerhalb des Loops erkannt. Keine weitere Übergabe; Chatverläufe prüfen.')

    def answer(self, identity, previous, stop):
        expected = None
        deadline = time.monotonic()+90
        while not stop.is_set():
            self.check_other_chats(identity)
            entry = self.poll(identity)
            turn = entry.get('latestTurn') or {}
            current = turn.get('id')
            if current and current != previous:
                if expected and current != expected:
                    raise ValueError('Ein weiterer Auftrag hat den Chat verändert. Automatik angehalten.')
                if expected is None:
                    self.service.debug.record('turn_detected',run=self.run.get('id'),target=identity,turn=current)
                expected = current
                if turn.get('status') == 'completed':
                    # Only forward the exact newly started turn, never an old answer.
                    self.service.debug.record('turn_completed',run=self.run.get('id'),target=identity,turn=current)
                    self.observed_turns[identity] = current
                    return self.service.workflow_answer(identity, current)
                if turn.get('status') not in ('inProgress', None):
                    raise ValueError('Chat wurde abgebrochen oder ist fehlgeschlagen.')
            if entry.get('thread',{}).get('status',{}).get('activeFlags'):
                raise ValueError('Chat benötigt Benutzereingabe. Ablauf angehalten.')
            if expected is None and time.monotonic()>deadline:
                raise ValueError('Neuer Durchlauf nicht eindeutig erkannt. Nicht erneut senden; Zielchat prüfen.')
            stop.wait(1)
        return None

    def execute(self, nodes, edges, current, stop):
        try:
            for identity in self.run['participants']:
                if stop.is_set():
                    break
                self.service.command('start', identity)
            self.observed_turns = {}
            for identity in self.run['participants']:
                baseline = self.idle(identity, stop)
                if baseline is None:
                    self.update(status='stopped', message='Gestoppt · keine weiteren Übergaben.')
                    return
                self.observed_turns[identity] = (baseline.get('latestTurn') or {}).get('id')
            text = None
            source = None
            counts = {}
            pending_counters = []
            current = edges[current]
            while not stop.is_set():
                node = nodes[current]
                self.update(node=current)
                if node['kind']=='counter':
                    pending_counters.append(current)
                elif node['kind']=='chat':
                    identity = node['chat']
                    self.check_other_chats(None)
                    before = self.idle(identity, stop)
                    if before is None or stop.is_set():
                        break
                    if text is None:
                        turn = before.get('latestTurn') or {}
                        if turn.get('status') != 'completed' or not turn.get('id'):
                            raise ValueError('Der Quellchat hat keine fertige letzte Antwort.')
                        text = self.service.workflow_answer(identity, turn['id'])
                        if not text or not text.strip():
                            raise ValueError('Die letzte Antwort des Quellchats ist leer.')
                        self.update(message='Letzte Antwort des Quellchats kopiert.')
                    else:
                        self.update(message='Antwort wird an den verbundenen Chat übergeben …')
                        if stop.is_set():
                            break
                        self.service.dispatch(identity,source,text,mode='loop',run=self.run.get('id'),source_turn=self.observed_turns.get(source),previous_turn=(before.get('latestTurn') or {}).get('id'))
                        self.service.forwarded()
                        self.update(message='Chat arbeitet · warte auf vollständige Antwort …')
                        text = self.answer(identity, (before.get('latestTurn') or {}).get('id'), stop)
                        if text is None:
                            break
                        limit_reached = False
                        for counter in pending_counters:
                            counts[counter] = counts.get(counter, 0) + 1
                            limit_reached |= counts[counter] >= nodes[counter]['limit']
                        if pending_counters:
                            self.update(counts=counts.copy(), message='Rückgabe abgeschlossen · Durchlauf gezählt.')
                            pending_counters.clear()
                        if limit_reached:
                            self.update(status='completed', message='Counter erreicht · automatisch gestoppt.')
                            return
                if node['kind']=='chat':
                    source = identity
                if current not in edges:
                    self.update(status='completed', message='Ende des verbundenen Pfads erreicht.')
                    return
                current = edges[current]
            self.update(status='stopped', message='Gestoppt · keine weiteren Übergaben.')
        except EmptyAnswer as error:
            self.update(status='stopped', message=str(error))
        except Exception as error:
            self.update(status='error', message=f'Ablauf angehalten: {error}')
