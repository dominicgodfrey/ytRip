"""ytRip local server. Binds 127.0.0.1 only, opens the browser, exits when the tab is gone and the queue is idle.

  python app/server.py [--debug] [--no-update] [--no-browser]
"""
import glob
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
SETTINGS = os.path.join(ROOT, 'settings.json')
PORT = 8765
DEBUG = '--debug' in sys.argv
GRACE = 15          # seconds with no open tab before exiting (covers reloads)
STARTUP_GRACE = 60  # time allowed for the browser to open the page

if sys.stderr is None:  # pythonw: no console, keep a log instead
    sys.stdout = sys.stderr = open(os.path.join(ROOT, 'ytRip.log'), 'w', encoding='utf-8', buffering=1)


def bind():
    try:
        return ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:  # already running: just show it
        webbrowser.open(f'http://127.0.0.1:{PORT}')
        sys.exit(0)


def self_update():
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', '--disable-pip-version-check',
                        '--retries', '0', '--timeout', '5', 'yt-dlp[default]', 'ytmusicapi'],
                       timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as e:
        print('update skipped:', e)


def find_ffmpeg():
    hits = glob.glob(os.path.join(ROOT, 'ffmpeg-*', '**', 'bin', 'ffmpeg.exe'), recursive=True)
    return os.path.dirname(hits[0]) if hits else None  # None -> yt-dlp looks on PATH


def load_settings():
    s = {'library': os.path.join(ROOT, 'tracks'), 'format': 'mp3'}
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s.update(json.load(f))
    except (FileNotFoundError, ValueError):
        pass
    return s


settings = load_settings()
# Liveness: each open tab holds one /api/live stream. Unlike timers, an open socket
# isn't throttled in background tabs, and it drops the moment the tab closes.
clients = 0
last_seen = time.time() + STARTUP_GRACE - GRACE
clients_lock = threading.Lock()
music = queue = None  # imported after the self-update


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, *a):
        if DEBUG:
            super().log_message(*a)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    def _guard(self, fn):
        try:
            self._json(fn())
        except Exception as e:
            if DEBUG:
                import traceback
                traceback.print_exc()
            self._json({'error': str(e).removeprefix('ERROR: ')[:300]}, 500)

    def _mark(self, obj):
        owned = queue.owned()
        for it in obj.get('items', []) + obj.get('tracks', []):
            if it.get('kind') == 'song':
                it['have'] = it['id'] in owned
        return obj

    def _live(self):
        global clients, last_seen
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        with clients_lock:
            clients += 1
        try:
            while True:  # a write to a closed tab raises, ending the stream
                self.wfile.write(b': ping\n\n')
                self.wfile.flush()
                time.sleep(5)
        except OSError:
            pass
        finally:
            with clients_lock:
                clients -= 1
                last_seen = time.time()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == '/api/live':
            return self._live()
        if u.path == '/api/state':
            return self._json({'jobs': queue.snapshot(), 'settings': settings})
        if u.path == '/api/search':
            return self._guard(lambda: self._mark(music.search(
                q['q'], q.get('tab', 'songs'), int(q.get('page', 1)), q.get('ytm') == '1', q.get('yt') == '1')))
        if u.path == '/api/open':
            def go():
                if 'url' in q:
                    r = music.resolve_url(q['url'])
                    if 'open' in r:
                        self._mark(r['open'])
                    return self._mark(r)
                return self._mark({'album': music.album, 'playlist': music.playlist,
                                   'artist': music.artist}[q['kind']](q['id']))
            return self._guard(go)
        if u.path.startswith('/api/'):
            return self._json({'error': 'not found'}, 404)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path).path
        if u == '/api/download':
            b = self._body()
            settings['format'] = b.get('format', settings['format'])
            save_settings()
            queue.add(b['tracks'], settings['format'])
            return self._json({'ok': True})
        if u == '/api/settings':
            b = self._body()
            if b.get('library'):
                path = os.path.abspath(os.path.expanduser(b['library']))
                os.makedirs(path, exist_ok=True)
                settings['library'] = path
            save_settings()
            return self._json({'settings': settings})
        if u == '/api/clear':
            queue.clear_finished()
            return self._json({'ok': True})
        if u == '/api/quit':
            self._json({'ok': True})
            threading.Thread(target=self.server.shutdown).start()
            return
        self._json({'error': 'not found'}, 404)


def save_settings():
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)


def watchdog(server):
    while True:
        time.sleep(3)
        if clients == 0 and time.time() - last_seen > GRACE and not queue.busy():
            print('no client and queue idle: shutting down')
            server.shutdown()
            return


def main():
    global music, queue
    server = bind()
    if '--no-browser' not in sys.argv:
        webbrowser.open(f'http://127.0.0.1:{PORT}')  # request waits in the backlog until we serve
    if '--no-update' not in sys.argv:
        self_update()
    import music as _music
    from downloads import Queue
    music = _music
    queue = Queue(find_ffmpeg(), lambda: settings['library'])
    os.makedirs(settings['library'], exist_ok=True)
    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    print(f'ytRip running on http://127.0.0.1:{PORT}')
    server.serve_forever()
    os._exit(0)  # don't wait on worker threads


if __name__ == '__main__':
    main()
