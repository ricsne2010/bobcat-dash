"""The service web page, served by the dash itself while SERVICE WI-FI is on (servicemode.py).

  /            Status: live gauges, active warnings, service due (updates every 2 s)
  /reports     Performance reports: engine time by throttle band, rpm, starts, hot shutdowns, temperatures
  /alarms      Alarm history (the list on the dash) and the archive
  /service     Service items, when they were last done, what's due
  /downloads   Everything as one zip, or one file at a time (CSV opens in Excel)
  /software    Upload an update zip, check it, install it; go back to the previous version; restart

Python's own http.server in a background thread: no extra packages, nothing from the internet (a phone on
the dash's Wi-Fi has none). It reads the dash's live objects; the only things it changes are the software
(engine off only) and turning the Wi-Fi off.
"""
import html
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import report
import updater
from service import DUE, SOON, clock_valid

log = logging.getLogger("web")
esc = html.escape
NAV = [("/", "Status"), ("/reports", "Reports"), ("/alarms", "Alarms"), ("/service", "Service"),
       ("/downloads", "Downloads"), ("/software", "Software")]
UPLOAD = "update-upload.zip"
MAX_UPLOAD = 60 * 1024 * 1024

STATUS_JS = """
<p class="you" id="you"></p>
<section class="tiles" id="tiles"></section>
<section class="panel" style="margin-top:14px"><h2>Warnings now</h2><div id="active" class="list"></div></section>
<section class="panel"><h2>Service</h2><div id="due" class="list"></div></section>
<section class="panel"><h2>Raspberry Pi</h2><dl class="pairs" id="pi"></dl></section>
<section class="panel"><h2>Service Wi-Fi</h2><p id="wifi"></p>
<button class="btn" onclick="post('/wifi-extend')">Extend 30 min</button>
<button class="btn gray" onclick="if(document.getElementById('sure').hidden){document.getElementById('sure').hidden=false}else{post('/wifi-off')}">Turn Wi-Fi off</button>
<span id="sure" class="hint" hidden> Press again to turn it off. This page stops working.</span><p id="done" class="hint"></p></section>
<script>
const E=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function post(u){const r=await fetch(u,{method:'POST',headers:{'X-Bobcat':'1'}});document.getElementById('done').textContent=await r.text();tick();}
async function tick(){try{const s=await (await fetch('/api/status')).json();
document.getElementById('tiles').innerHTML=s.tiles.map(t=>`<div class="tile ${t[2]}"><div class="lbl">${E(t[0])}</div><div class="val">${E(t[1])}</div></div>`).join('');
document.getElementById('active').innerHTML=s.active.length?s.active.map(a=>`<a><span>${E(a[0])} <small>${E(a[2])}</small></span><span class="pill ${a[1]}">${E(a[3])}</span></a>`).join(''):'<p class="hint">None. All clear.</p>';
document.getElementById('due').innerHTML=s.due.length?s.due.map(a=>`<a href="/service"><span>${E(a[0])}</span><span class="pill ${a[1]}">${E(a[2])}</span></a>`).join(''):'<p class="hint">Nothing due.</p>';
document.getElementById('pi').innerHTML=s.pi.map(p=>`<dt>${E(p[0])}</dt><dd>${E(p[1])}</dd>`).join('');
document.getElementById('wifi').textContent=s.wifi;document.getElementById('you').textContent=s.you||'';}catch(e){document.getElementById('wifi').textContent='Lost contact with the dash.';}}
tick();setInterval(tick,2000);
</script>"""

SOFTWARE_JS = """
<script>
async function up(){const f=document.getElementById('zip').files[0];if(!f)return;
const m=document.getElementById('m');m.className='msg';m.textContent='Uploading '+f.name+' ...';
const r=await fetch('/software/upload',{method:'POST',headers:{'X-Bobcat':'1','X-Filename':f.name},body:f});
const j=await r.json();if(!j.ok){m.className='msg bad';m.textContent=j.error;return;}
m.className='msg good';m.innerHTML='Checked: version <b>'+j.version+'</b> ('+j.build+'), '+j.files+' files, all Python files compile.';
document.getElementById('inst').disabled=false;}
async function act(u,ask,mid){const m=document.getElementById(mid||'m');const c=document.getElementById(mid=='m2'?'code2':'code');
if(!/^[0-9]+$/.test(c.value)){m.className='msg bad';m.textContent='Enter the maintenance code first (the one used on the dash).';c.focus();return;}
if(!confirm(ask))return;m.className='msg';m.textContent='Working ...';
const r=await fetch(u,{method:'POST',headers:{'X-Bobcat':'1','X-Code':c.value}});const t=await r.text();c.value='';
m.className='msg '+(r.ok?'good':'bad');m.textContent=t;if(r.ok)setTimeout(()=>location.reload(),15000);}
</script>"""


def device_of(ua):
    """'iPhone · Safari' from a browser's User-Agent line (a best guess: browsers can say what they like)."""
    ua = ua or ""
    dev = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android phone" if "Android" in ua and "Mobile" in ua
           else "Android tablet" if "Android" in ua else "Windows" if "Windows" in ua else "Chromebook" if "CrOS" in ua
           else "Mac" if "Macintosh" in ua else "Linux" if "Linux" in ua else "")
    br = ("Edge" if "Edg/" in ua else "Samsung Internet" if "SamsungBrowser" in ua else "Opera" if "OPR/" in ua
          else "Firefox" if "Firefox/" in ua or "FxiOS" in ua else "Chrome" if "Chrome/" in ua or "CriOS" in ua
          else "Safari" if "Safari/" in ua else "curl" if ua.startswith("curl") else "")
    return " · ".join(x for x in (dev, br) if x) or "unknown device"


CODE_FIELD = ('<p><label>Maintenance code <input type="password" id="{id}" inputmode="numeric" pattern="[0-9]*" '
              'maxlength="8" autocomplete="off" size="8" style="font:inherit;padding:8px;border-radius:8px;'
              'border:1px solid var(--line);background:var(--panel);color:var(--ink);margin-left:6px"></label></p>')


def _state_word(state):
    return {"ok": "OK", "warn": "WARNING", "alarm": "ALARM", "unknown": "NO SIGNAL"}.get(state, state.upper())


class Handler(BaseHTTPRequestHandler):
    ctx = None                       # set by WebServer
    server_version = "BobcatDash"

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    # -- plumbing

    def _send(self, body, ctype="text/html; charset=utf-8", code=200, name=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if name:
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        self.wfile.write(body)

    def _page(self, title, body, active):
        c = self.ctx
        foot = (f'S.S.O.M.S v{esc(c["version"])} - {c["hours"]():.1f} engine hours - '
                + esc(c["wifi_text"]()))
        self._send(report.page(title, body, NAV, active, f'v{c["version"]}', foot))

    def _seen(self):
        """Note who's asking (the dash's Wi-Fi pop-up lists the devices connected now)."""
        self.ctx["touch"]()
        self.ctx.setdefault("clients", {})[self.client_address[0]] = (device_of(self.headers.get("User-Agent")),
                                                                       time.monotonic())

    def do_GET(self):
        self._seen()
        url = urlparse(self.path)
        q = parse_qs(url.query)
        route = {"/": self.status, "/api/status": self.api_status, "/reports": self.reports, "/alarms": self.alarms,
                 "/service": self.service, "/downloads": self.downloads, "/software": self.software}.get(url.path)
        try:
            if route:
                route(q)
            elif url.path.startswith("/download/"):
                self.download(url.path[len("/download/"):])
            else:
                self._send("Not found", "text/plain", 404)
        except Exception as e:                       # a broken page must never take the dash down
            log.exception("web page %s failed", url.path)
            self._send(f"Error: {e}", "text/plain; charset=utf-8", 500)

    def do_POST(self):
        self._seen()
        if self.headers.get("X-Bobcat") != "1":
            self._send("Use the buttons on the page.", "text/plain", 403)
            return
        path = urlparse(self.path).path
        try:
            if path == "/software/upload":
                self.upload()
            elif path in ("/software/install", "/software/restore", "/restart"):
                self.software_action(path)
            elif path == "/wifi-extend":
                self.ctx["wifi_extend"]()
                self._send("Extended. " + self.ctx["wifi_text"](), "text/plain; charset=utf-8")
            elif path == "/wifi-off":
                self._send("Turning the service Wi-Fi off. You can close this page.", "text/plain")
                self.ctx["wifi_off"]()
            else:
                self._send("Not found", "text/plain", 404)
        except Exception as e:
            log.exception("web action %s failed", path)
            self._send(f"Error: {e}", "text/plain; charset=utf-8", 500)

    # -- pages

    def status(self, q):
        self._page("Status", STATUS_JS, "/")

    def api_status(self, q):
        live = dict(self.ctx["live"]())
        live["you"] = f'You: {device_of(self.headers.get("User-Agent"))} ({self.client_address[0]})'
        self._send(json.dumps(live), "application/json")

    def reports(self, q):
        c = self.ctx
        period = q.get("p", ["30"])[0]
        if period not in dict(report.PERIODS):
            period = "30"
        usage = c["usage"]
        body = report.report_body(dict(usage.days), usage.bands(), list(c["events"].events), period,
                                  c["cfg"].get("temperature", {}).get("units", "F").upper(),
                                  max_rpm=c["cfg"].get("tach", {}).get("max_rpm", 3500))
        if not clock_valid():
            body = '<p class="msg bad">The Pi\'s clock isn\'t set, so new days are filed under "no-date".</p>' + body
        self._page("Performance reports", body, "/reports")

    def alarms(self, q):
        show_all = q.get("all", ["0"])[0] == "1"
        evs = self.ctx["events"].archive() if show_all else self.ctx["events"].newest_first()
        tabs = (f'<nav class="periods"><a href="/alarms" class="{"" if show_all else "on"}">History list</a>'
                f'<a href="/alarms?all=1" class="{"on" if show_all else ""}">All alarms (archive)</a></nav>')
        if not evs:
            body = tabs + '<p class="empty">Nothing recorded.</p>'
        else:
            rows = "".join(
                f'<tr><td>{esc(report.when(e.get("t")) or "date not set")}</td><td>{e.get("h", 0):.1f} h</td>'
                f'<td>{esc(e["what"])}</td><td><span class="pill {e["level"]}">{_state_word(e["level"])}</span></td>'
                f'<td>{esc(e.get("detail") or "")}</td><td>{esc(report.hm(e["dur_s"]) if e.get("dur_s") else "still on")}</td>'
                f'<td>{"cleared" if e.get("cleared") else ""}</td></tr>' for e in evs)
            body = (tabs + '<section class="panel"><div class="scroll"><table><tr><th>When</th><th>Meter</th>'
                    '<th>What</th><th>Level</th><th>Detail</th><th>Lasted</th><th></th></tr>' + rows +
                    '</table></div></section><p class="hint">Clear alarms on the dash (HISTORY screen). '
                    'Cleared ones stay in the archive.</p>')
        self._page("Alarms", body, "/alarms")

    def service(self, q):
        svc, hours = self.ctx["service"], self.ctx["hours"]()
        rows = []
        for it, state, left, days in svc.status(hours):
            s = svc.state.get(it["id"], {})
            word, cls = ("DUE", "due") if state == DUE else ("SOON", "soon") if state == SOON else ("OK", "ok")
            left_txt = f"overdue {-left:.1f} h" if left <= 0 else f"{left:.1f} h"
            if days is not None:
                left_txt += f", {days:.0f} days" if days > 0 else ", overdue by date"
            last = (f'{s["done_h"]:.1f} h' + (f' ({esc(report.when(s.get("done_t"))[:10])})' if s.get("done_t") else "")
                    + (" install" if s.get("baseline") else "")) if s else "-"
            rows.append(f'<tr><td><b>{esc(it["name"])}</b><br><small class="hint">{esc(svc.task(it))}</small></td>'
                        f'<td>{svc.interval(it):g} h</td><td>{last}</td><td>{left_txt}</td>'
                        f'<td><span class="pill {cls}">{word}</span></td></tr>')
        hist = svc.completed()
        done = "".join(f'<tr><td>{esc(h["name"])}</td><td>{h["h"]:.1f} h</td><td>{esc(report.when(h.get("t")) or "-")}</td></tr>'
                       for h in hist[:100]) or '<tr><td colspan="3">None recorded yet.</td></tr>'
        ci = svc.climate_info()
        body = (f'<p>Engine hours <b>{hours:.1f}</b>. Climate <b>{esc(ci.get("label", ""))}</b> '
                f'(engine oil {esc(ci.get("oil_grade", ""))}). Mark jobs done on the dash (SERVICE screen).</p>'
                '<section class="panel"><div class="scroll"><table><tr><th>Item</th><th>Every</th><th>Last done</th>'
                '<th>Left</th><th></th></tr>' + "".join(rows) + '</table></div></section>'
                '<section class="panel"><h2>Completed</h2><table><tr><th>Item</th><th>Meter</th><th>When</th></tr>'
                + done + "</table></section>")
        self._page("Service", body, "/service")

    def downloads(self, q):
        name = report.export_name(self.ctx["hours"]())
        items = [("export.zip", f"Everything (bobcat-{name}.zip)", "the report, all CSV files, the settings, the dash's data and log"),
                 ("report.html", "Performance report", "all time, opens in any browser"),
                 ("usage-daily.csv", "Usage by day", "engine time by throttle band, starts, temperatures"),
                 ("alarms.csv", "Alarms", "every alarm and warning recorded"),
                 ("service-status.csv", "Service status", "each item: last done, hours left"),
                 ("service-done.csv", "Service done", "jobs marked done on the dash"),
                 ("config.toml", "Settings", "the dash's config.toml"),
                 ("dash-log.txt", "Dash log", "for trouble-shooting")]
        body = ('<section class="panel list">' + "".join(
            f'<a href="/download/{f}"><span><b>{t}</b><br><small>{d}</small></span><span>Download</span></a>'
            for f, t, d in items) + "</section>")
        self._page("Downloads", body, "/downloads")

    def download(self, name):
        c = self.ctx
        stamp = report.export_name(c["hours"]())
        if name == "export.zip":
            self._send(report.bundle_zip(c), "application/zip", name=f"bobcat-{stamp}.zip")
            return
        files = report.bundle(c)
        if name not in files:
            self._send("Not found", "text/plain", 404)
            return
        ctype = {"html": "text/html; charset=utf-8", "csv": "text/csv; charset=utf-8"}.get(name.rsplit(".", 1)[-1],
                                                                                          "text/plain; charset=utf-8")
        base, ext = os.path.splitext(name)
        self._send(files[name], ctype, name=f"bobcat-{base}-{stamp}{ext}")

    def software(self, q):
        c = self.ctx
        repo = c["repo"]
        v, b = updater.current_version(repo)
        prev = updater.previous(repo)
        running = c["live"]().get("running")
        hist = updater.history(c["data_dir"])
        rows = "".join(f'<tr><td>{esc(report.when(h.get("t")) or "-")}</td><td>{esc(h["what"])}</td>'
                       f'<td>{esc(h["from"])}</td><td>{esc(h["to"])}</td></tr>' for h in reversed(hist[-20:]))
        warn = '<p class="msg bad">The engine is running: stop it before installing or restarting.</p>' if running else ""
        body = (warn + f'<section class="panel"><h2>Installed</h2><p>Version <b>{esc(v)}</b> ({esc(b)})'
                + (f'. Previous version kept: <b>{esc(prev[0])}</b> ({esc(prev[1])})' if prev else "") + "</p>"
                + CODE_FIELD.format(id="code2") +
                '<button class="btn gray" onclick="act(\'/restart\',\'Restart the dash software now?\',\'m2\')">Restart dash</button> '
                + ('<button class="btn gray" onclick="act(\'/software/restore\',\'Go back to the previous version? '
                   'The dash restarts.\',\'m2\')">Go back to previous version</button>' if prev else "") + '<div id="m2"></div></section>'
                '<section class="panel"><h2>Update</h2><ol><li>On a computer or phone with internet, download the zip from '
                'GitHub (the project page: <b>Code</b> &gt; <b>Download ZIP</b>, or a release).</li>'
                '<li>Join the dash\'s Wi-Fi, open this page and pick the zip.</li>'
                '<li>The dash checks it. Then <b>Install</b>: your settings (config.toml) and splash pictures are kept, '
                'the running version is kept as the previous version, and the dash restarts (about 15 s).</li></ol>'
                '<p><input type="file" id="zip" accept=".zip" onchange="up()"></p>'
                + CODE_FIELD.format(id="code") +
                f'<button class="btn" id="inst" disabled onclick="act(\'/software/install\',\'Install this version? '
                f'The dash restarts.\')">Install</button><div id="m"></div>'
                '<p class="hint">Installing, going back and restarting need the maintenance code (the one for SERVICE '
                'WI-FI on the dash). Wrong codes count toward the same lock and show in the alarm history.</p></section>'
                + (f'<section class="panel"><h2>Update history</h2><table><tr><th>When</th><th></th><th>From</th>'
                   f'<th>To</th></tr>{rows}</table></section>' if rows else "") + SOFTWARE_JS)
        self._page("Software", body, "/software")

    # -- actions

    def upload(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_UPLOAD:
            self._send(json.dumps({"ok": False, "error": f"pick a zip under {MAX_UPLOAD // 2 ** 20} MB"}), "application/json")
            return
        path = os.path.join(self.ctx["data_dir"], UPLOAD)
        with open(path + ".part", "wb") as f:
            left = n
            while left:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        os.replace(path + ".part", path)
        try:
            info = updater.check(path)
            self._send(json.dumps({"ok": True, **info}), "application/json")
        except updater.UpdateError as e:
            os.remove(path)
            self._send(json.dumps({"ok": False, "error": f"That zip won't do: {e}"}), "application/json")

    def _code_ok(self):
        """The maintenance code sent with a software action (X-Code). Sends the refusal itself when it's not OK."""
        c, code = self.ctx, self.ctx["code"]
        entered = (self.headers.get("X-Code") or "").strip()
        if not code.is_set():
            self._send("No maintenance code yet: make one at the dash first (SYSTEM > OK).", "text/plain", 403)
            return False
        locked = code.locked_for()
        if locked:
            self._send(f"Too many wrong codes: try again in {int(locked // 60)}:{int(locked % 60):02d}.", "text/plain", 423)
            return False
        if not (entered.isdigit() and len(entered) == code.digits):     # not a guess: no count, no record
            self._send(f"Enter the {code.digits}-digit maintenance code.", "text/plain", 400)
            return False
        if code.check(entered):
            return True
        locked = code.locked_for()
        who = device_of(self.headers.get("User-Agent"))
        c["events"].note("MAINTENANCE CODE", "warn", f"wrong code on the web page ({who})" + (", locked" if locked else ""),
                         c["hours"]())
        left = code.tries_left()
        self._send(f"Wrong code. Locked for {locked / 60:.0f} min." if locked else
                   f"Wrong code. {left} more {'try' if left == 1 else 'tries'}, then it locks.", "text/plain", 403)
        return False

    def software_action(self, path):
        c = self.ctx
        if c["live"]().get("running"):
            self._send("The engine is running: stop it first.", "text/plain", 409)
            return
        if not self._code_ok():
            return
        try:
            if path == "/software/install":
                up = os.path.join(c["data_dir"], UPLOAD)
                if not os.path.isfile(up):
                    self._send("Upload a zip first.", "text/plain", 400)
                    return
                info = updater.install(up, c["repo"], c["data_dir"])
                os.remove(up)
                msg = f"Installed version {info['version']}. The dash is restarting: this page reloads in 15 s."
            elif path == "/software/restore":
                v = updater.restore(c["repo"], c["data_dir"])
                msg = f"Back to version {v[0]}. The dash is restarting: this page reloads in 15 s."
            else:
                msg = "The dash is restarting: this page reloads in 15 s."
        except updater.UpdateError as e:
            self._send(f"Not done: {e}", "text/plain; charset=utf-8", 400)
            return
        self._send(msg, "text/plain; charset=utf-8")
        c["restart"]()


class WebServer:
    def __init__(self, ctx, port):
        Handler.ctx = ctx
        self.httpd = None
        self.port = port
        self.error = None

    def start(self):
        for port in (self.port, 8080) if self.port != 8080 else (8080,):
            try:
                self.httpd = ThreadingHTTPServer(("", port), Handler)
                self.httpd.daemon_threads = True
                self.port = port
                break
            except OSError as e:
                self.error = f"port {port}: {e.strerror}"
                log.warning("web page can't use %s", self.error)
        if not self.httpd:
            return False
        threading.Thread(target=self.httpd.serve_forever, name="web", daemon=True).start()
        log.info("service web page on port %d", self.port)
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
