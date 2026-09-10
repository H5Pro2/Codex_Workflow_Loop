"""Use the bundled Codex App Tools MCP, connected to the running desktop app."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


class BridgeError(RuntimeError):
    pass


def resolve_runtime(config):
    result = dict(config)
    for key in ('node', 'module'):
        saved = Path(result.get(key, ''))
        if saved.is_file():
            continue
        candidates = []
        if key == 'node':
            env = os.environ.get('CODEX_MCP_NODE_PATH')
            if env:
                candidates.append(Path(env))
            root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'OpenAI/Codex/runtimes/cua_node'
            candidates.extend(sorted(root.glob('*/bin/node.exe'), key=lambda p:p.stat().st_mtime, reverse=True))
        elif saved.name == 'server.mjs' and saved.parent.parent.name == 'codex-app-tools':
            candidates.extend(sorted(saved.parent.parent.glob('*/server.mjs'), key=lambda p:p.stat().st_mtime, reverse=True))
        match = next((p for p in candidates if p.is_file()), None)
        if match is None:
            raise BridgeError('Codex-Runtime oder App-Modul fehlt. Codex öffnen und Workflow Loop aus der aktuellen Codex-Umgebung neu starten.')
        result[key] = str(match)
    if not result.get('pipe') or not result.get('thread'):
        raise BridgeError('Die lokale Codex-Verbindung muss neu eingerichtet werden.')
    return result


class Bridge:
    def __init__(self, notify=lambda *args: None):
        self.notify = notify
        self.process = None
        self.pending = {}
        self.counter = 0
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()
        self.active = {}
        self.context = None

    def ensure(self):
        with self.start_lock:
            if self.process and self.process.poll() is None:
                return
            config_path = Path(__file__).resolve().parents[1] / 'data' / 'app-connection.json'
            try:
                config = json.loads(config_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise BridgeError('Die Verbindung zur laufenden Codex-App ist noch nicht eingerichtet.')
            config = resolve_runtime(config)
            self.context = config['thread']
            environment = os.environ.copy()
            environment['CODEX_APP_TOOLS_PIPE_PATH'] = config['pipe']
            self.process = subprocess.Popen([config['node'], config['module']], env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            threading.Thread(target=self.read, args=(self.process,), daemon=True).start()
            try:
                self.request('initialize', {'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'workflow-loop','version':'1.0.0'}})
                self.write({'method':'notifications/initialized'})
                catalog = self.request('tools/list', {})
                if not any(t['name']=='send_message_to_thread' for t in catalog.get('tools', [])):
                    raise BridgeError('Die Codex-App bietet die Sendefunktion nicht an.')
            except Exception:
                self.process.terminate()
                raise

    def preflight(self, identity):
        # Read-only check: never retry a message dispatch.
        try:
            result = self.call('wait_threads', {'targets':[{'threadId':identity}], 'timeoutMs':0})
        except (OSError, BridgeError) as error:
            self.close()
            raise BridgeError('Codex-Verbindung nicht bereit. Codex öffnen; gegebenenfalls Workflow Loop aus der aktuellen Codex-Umgebung neu starten. Der Zähler bleibt erhalten. ' + str(error)) from error
        polls = result.get('polls', [])
        if not polls or polls[0].get('thread', {}).get('id') != identity:
            raise BridgeError('Codex bestätigt den Quellchat nicht. Der Zähler bleibt erhalten.')

    def write(self, message):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                raise BridgeError('Codex-App-Verbindung beendet. Verbindung neu einrichten lassen.')
            self.process.stdin.write(json.dumps({'jsonrpc':'2.0', **message}, ensure_ascii=False)+'\n')
            self.process.stdin.flush()

    def request(self, method, params):
        channel = queue.Queue()
        with self.lock:
            self.counter += 1
            identity = self.counter
            self.pending[identity] = channel
        try:
            self.write(dict(id=identity, method=method, params=params))
            try:
                response = channel.get(timeout=45)
            except queue.Empty:
                raise BridgeError('Keine eindeutige Codex-BestÃ¤tigung. Vor erneutem Senden den Zielchat prÃ¼fen.')
            if 'error' in response:
                raise BridgeError(response['error'].get('message','Codex-Anfrage fehlgeschlagen'))
            return response.get('result', {})
        finally:
            with self.lock:
                self.pending.pop(identity, None)

    def read(self, process):
        try:
            for line in process.stdout:
                try:
                    response = json.loads(line)
                except ValueError:
                    continue
                with self.lock:
                    channel = self.pending.get(response.get('id'))
                if channel:
                    channel.put(response)
        finally:
            with self.lock:
                for channel in self.pending.values():
                    channel.put({'error':{'message':'Verbindung zur Codex-App unterbrochen; Versandstatus prÃ¼fen.'}})

    def call(self, name, arguments):
        self.ensure()
        result = self.request('tools/call', {'name':name,'arguments':arguments,'_meta':{'threadId':self.context}})
        texts = [item.get('text','') for item in result.get('content',[]) if item.get('type')=='text']
        if result.get('isError'):
            raise BridgeError('\n'.join(texts) or 'Die Codex-App hat die Anfrage abgelehnt.')
        for text in texts:
            try:
                return json.loads(text)
            except ValueError:
                continue
        raise BridgeError('Die Codex-App hat keine auswertbare BestÃ¤tigung geliefert.')

    def send(self, target, text):
        # Read the app's own live state; no independent app-server is launched.
        status = self.call('wait_threads', {'targets':[{'threadId':target}],'timeoutMs':0})
        polls = status.get('polls',[])
        if not polls:
            raise BridgeError('Zielchat in der laufenden Codex-App nicht bestÃ¤tigt.')
        entry = polls[0]
        if entry.get('thread',{}).get('id') != target:
            raise BridgeError('Die Codex-App hat einen anderen Zielchat zurÃ¼ckgegeben.')
        if entry.get('thread',{}).get('status',{}).get('type')=='active' or entry.get('latestTurn',{}).get('status')=='inProgress':
            raise BridgeError('Der Zielchat arbeitet bereits.')
        response = self.call('send_message_to_thread', {'threadId':target,'prompt':text})
        if response.get('threadId') != target:
            raise BridgeError('Versand nicht eindeutig bestÃ¤tigt. Zielchat vor erneutem Versuch prÃ¼fen.')
        return response

    def close(self):
        # Only closes the transport helper. The desktop app owns submitted turns.
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
