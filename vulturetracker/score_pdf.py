"""Print the existing score renderer with an installed headless Chromium browser."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

from .fileio import link_new


def browser_executable():
    candidates = [os.environ.get('VT_CHROMIUM', '')]
    for base in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
        root = os.environ.get(base)
        if root:
            candidates += [str(Path(root) / 'Microsoft/Edge/Application/msedge.exe'),
                           str(Path(root) / 'Google/Chrome/Application/chrome.exe')]
    candidates += [shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome', 'microsoft-edge')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise ValueError('PDF delivery needs installed Microsoft Edge, Chrome or Chromium (VT_CHROMIUM can select it)')


def write_pdf(view, output, settings, cancel, track=None):
    """An immutable snapshot; no desktop window or current-song server state is used."""
    if not view.get('score'):
        raise ValueError('PDF delivery requires an authored native score')
    if cancel.is_set():
        raise ValueError('PDF delivery cancelled')
    output = Path(output)
    if output.exists():
        raise ValueError(f'PDF output already exists: {output}')
    browser = browser_executable()
    token = secrets.token_urlsafe(32)
    web = Path(__file__).parent / 'web'
    payload = json.dumps(view).encode('utf-8')
    config = json.dumps(dict(paper=settings['paper'], notation=settings['notation'], scale=settings['scale'], track=track))
    page = ('''<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/web/tablature.css">
<script src="/web/alphaTab.min.js"></script><script src="/web/engine-core.js"></script>
<script src="/web/tablature.js"></script></head><body><main id="score-print"></main><script>
(async()=>{try{
const view=await (await fetch('/SNAPSHOT')).json(),cfg=CONFIG,root=document.getElementById('score-print');
VultureTab.mountPrint(root,view);
const form=root.querySelector('form');
for(const key of ['paper','notation','scale'])form.elements.namedItem(key).value=cfg[key];
if(cfg.track!==null)for(const input of form.querySelectorAll('[name=track]'))input.checked=input.value===cfg.track;
form.dispatchEvent(new Event('submit',{cancelable:true}));
}catch(e){document.body.dataset.failure=e.message}})();
</script></body></html>'''.replace('SNAPSHOT', token + '/snapshot').replace('CONFIG', config)).encode('utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            route = self.path.split('?', 1)[0]
            if route == '/' + token:
                data, mime = page, 'text/html; charset=utf-8'
            elif route == '/' + token + '/snapshot':
                data, mime = payload, 'application/json'
            elif route.startswith('/web/'):
                path = (web / route[5:]).resolve()
                if not path.is_relative_to(web.resolve()) or not path.is_file():
                    self.send_error(404)
                    return
                data, mime = path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except ConnectionError:
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        temporary = tempfile.TemporaryDirectory(prefix='vt-score-pdf-')
        try:
            root = Path(temporary.name)
            pdf = root / 'score.pdf'
            args = [browser, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                    '--disable-extensions', '--disable-background-networking', '--no-pdf-header-footer',
                    '--run-all-compositor-stages-before-draw', '--virtual-time-budget=20000',
                    '--user-data-dir=' + str(root / 'profile'), '--print-to-pdf=' + str(pdf), '--dump-dom',
                    f'http://127.0.0.1:{server.server_port}/{token}']
            if os.name == 'nt' and Path(browser).name.lower() == 'msedge.exe':
                # Edge's compatibility relaunch exits the owned parent with 0,
                # losing stdout/PDF completion and leaving a detached child.
                # The same launch flag is used by Playwright's Edge runner.
                args.insert(1, '--edge-skip-compat-layer-relaunch')
            with (root / 'dom.html').open('wb') as stdout, (root / 'browser.log').open('wb') as stderr:
                proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, start_new_session=os.name != 'nt',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                deadline = time.monotonic() + 90
                try:
                    while proc.poll() is None:
                        if cancel.is_set():
                            raise ValueError('PDF delivery cancelled')
                        if time.monotonic() >= deadline:
                            raise ValueError('PDF score rendering timed out')
                        cancel.wait(.1)
                finally:
                    if proc.poll() is None:
                        if os.name == 'nt':
                            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                        else:
                            import signal
                            os.killpg(proc.pid, signal.SIGTERM)
                        if proc.poll() is None:
                            proc.kill()
                    proc.wait()
            dom = (root / 'dom.html').read_text(encoding='utf-8', errors='replace')
            # Chromium may print an error/unfinished page successfully: only publish completed engraving.
            if proc.returncode or 'data-pages="' not in dom or 'Cannot print:' in dom or 'data-failure=' in dom:
                import re
                reason = re.search(r'Cannot print: ([^<]+)|data-failure="([^"]+)"', dom)
                detail = (reason[1] or reason[2]) if reason else f'browser exit {proc.returncode}; no completed score'
                if not reason:
                    with (root / 'browser.log').open('rb') as log:
                        log.seek(0, os.SEEK_END)
                        log.seek(max(0, log.tell() - 4096))
                        diagnostic = log.read().decode('utf-8', errors='replace')
                    diagnostic = diagnostic.replace(token, '<token>').replace(str(root), '<pdf-temp>').strip()
                    if diagnostic:
                        detail += '; browser stderr: ' + diagnostic
                raise ValueError('PDF rendering did not finish: ' + detail)
            if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
                raise ValueError('Browser did not produce a PDF')
            if cancel.is_set():
                raise ValueError('PDF delivery cancelled')
            output.parent.mkdir(parents=True, exist_ok=True)
            link_new(pdf, output)
        finally:
            # Chromium children release profile handles just after the owned process tree exits.
            for delay in (0, .1, .3, 1, 2):
                if delay:
                    time.sleep(delay)
                try:
                    temporary.cleanup()
                    break
                except PermissionError:
                    if delay == 2:
                        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return str(output)
