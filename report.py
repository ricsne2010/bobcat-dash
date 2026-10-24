"""Reports and exports, shared by the service web page and the USB stick copy.

Everything here only reads: the usage log (usage.py), the alarm history (events.py), the service records
(service.py). The HTML is self-contained (no internet on the dash's own Wi-Fi): inline CSS and SVG charts,
so the report.html copied to a USB stick opens on any computer.
"""
import csv
import datetime
import html
import io
import json
import os
import time
import zipfile

import settings
from service import clock_valid

PERIODS = (("7", "7 days"), ("30", "30 days"), ("365", "12 months"), ("all", "All time"))
# The VH4D works at full throttle (the governor holds the speed); idle is for warm-up and cool-down. Part throttle is
# for warming a cold engine, pump priming or setting the timing, so a lot of time there is flagged.
BAND_COLORS = {"idle_s": "var(--idle)", "work_s": "var(--part)", "full_s": "var(--full)", "over_s": "var(--over)"}
BAND_NAMES = {"idle_s": "Idle", "work_s": "Part throttle", "full_s": "Full throttle", "over_s": "Overspeed"}
PART_WARN = 0.10          # part throttle above this share of engine time: amber card
SUMS = ("key_s", "run_s", "idle_s", "work_s", "full_s", "over_s", "crank_s", "starts", "cranks", "stops", "hot_stops")
esc = html.escape


# ---------------------------------------------------------------- numbers

def hm(s):
    """Seconds -> '12 h 05 min' / '35 min'."""
    m = int(round((s or 0) / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def lasted(s):
    """How long an alarm lasted, to the second: '4 s', '2 min 05 s', '1 h 02 min 05 s'."""
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min {s % 60:02d} s"


def pct(a, b):
    return f"{100 * a / b:.0f} %" if b else "-"


def temp(c, units):
    return "-" if c is None else settings.fmt(c, space=True, u=units)


def day_of(t):
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t and clock_valid(t) else "no-date"


def select(days, period, today=None):
    """The day keys in the period, oldest first ('no-date' only in All time)."""
    if period == "all":
        return sorted(days)
    today = today or datetime.date.today()
    first = (today - datetime.timedelta(days=int(period) - 1)).isoformat()
    return sorted(k for k in days if k != "no-date" and first <= k <= today.isoformat())


def total(recs):
    t = {k: 0 for k in SUMS}
    t["hist"] = {}
    for r in recs:
        for k in SUMS:
            t[k] += r.get(k, 0)
        for b, s in r.get("hist", {}).items():
            t["hist"][b] = t["hist"].get(b, 0) + s
        for k, f in (("box_max", max), ("box_min", min), ("amb_max", max), ("amb_min", min), ("pi_max", max), ("pi_min", min),
                     ("v_run_min", min), ("v_run_max", max)):
            if r.get(k) is not None:
                t[k] = f(t[k], r[k]) if k in t else r[k]
    return t


def buckets(days, period, today=None):
    """[(label, totals)] for the bar chart: every day for 7 / 30 days, months for longer."""
    today = today or datetime.date.today()
    if period in ("7", "30"):
        n = int(period)
        out = []
        for i in range(n - 1, -1, -1):
            d = today - datetime.timedelta(days=i)
            out.append((d.strftime("%a %d" if n <= 7 else "%d"), total([days.get(d.isoformat(), {})])))
        return out
    keys = [k for k in select(days, period, today) if k != "no-date"]
    if not keys:
        return []
    months = {}
    for k in keys:
        months.setdefault(k[:7], []).append(days[k])
    y, m = map(int, keys[0][:7].split("-"))
    out = []
    while (y, m) <= (today.year, today.month):
        key = f"{y:04d}-{m:02d}"
        out.append((datetime.date(y, m, 1).strftime("%b %y"), total(months.get(key, []))))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def daily(days, period, today=None):
    """[(date, record)] one per calendar day of the period (days without use: {}), oldest first."""
    today = today or datetime.date.today()
    if period in ("7", "30"):
        first = today - datetime.timedelta(days=int(period) - 1)
    else:
        keys = [k for k in select(days, period, today) if k != "no-date"]
        if not keys:
            return []
        first = datetime.date.fromisoformat(keys[0])
    n = (today - first).days + 1
    return [(first + datetime.timedelta(days=i), days.get((first + datetime.timedelta(days=i)).isoformat(), {}))
            for i in range(n)]


def temp_val(c, units):
    return None if c is None else (c * 9 / 5 + 32 if units == "F" else c)


# ---------------------------------------------------------------- charts (inline SVG)

def svg_lines(dates, series, unit, aria, decimals=0):
    """A line chart by day. series: [(name, css colour, [value or None per date])]. A day without a value
    breaks the line (no slope down to zero)."""
    W, H, L, R, T, B = 760, 250, 48, 12, 12, 30
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if not vals or len(dates) < 2:
        return '<p class="hint">Not enough days recorded for a chart yet.</p>'
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1.0 if decimals else 10.0)
    raw = span / 4
    mag = 10 ** int(f"{raw:e}".split("e")[1])
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    y0 = (lo // step) * step
    y1 = y0 + step * (int((hi - y0) / step) + 1)
    n = len(dates)
    def X(i):
        return L + (W - L - R) * i / (n - 1)
    def Y(v):
        return H - B - (H - B - T) * (v - y0) / (y1 - y0)
    out = [f'<div class="chartwrap"><svg viewBox="0 0 {W} {H}" class="chart lines" role="img" aria-label="{esc(aria)}">']
    v = y0
    while v <= y1 + 1e-9:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" class="ax" text-anchor="end">{v:.{decimals}f}{esc(unit)}</text>')
        v += step
    every = max(1, round(n / 8))
    for i, d in enumerate(dates):
        if i % every == 0 or i == n - 1 and (n - 1) % every > every / 2:
            out.append(f'<text x="{X(i):.1f}" y="{H - 8}" class="ax" text-anchor="middle">{d.strftime("%b %d")}</text>')
    dots = n <= 62
    for name, col, vs in series:
        path, gaps, pen, last = [], [], False, None
        for i, v in enumerate(vs):
            if v is None:
                pen = False
                continue
            if not pen and last is not None:          # across days without use: a faint dashed line
                gaps.append(f"M{X(last[0]):.1f},{Y(last[1]):.1f} L{X(i):.1f},{Y(v):.1f}")
            path.append(f'{"L" if pen else "M"}{X(i):.1f},{Y(v):.1f}')
            pen, last = True, (i, v)
        if gaps:
            out.append(f'<path d="{" ".join(gaps)}" fill="none" stroke="{col}" stroke-width="1.4" stroke-dasharray="3 4" opacity=".55"/>')
        out.append(f'<path d="{" ".join(path)}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
        for i, v in enumerate(vs):
            if v is not None and (dots or i == 0 or vs[i - 1] is None):
                out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{3 if dots else 2}" fill="{col}">'
                           f'<title>{esc(name)} {dates[i].strftime("%b %d")}: {v:.{decimals}f}{esc(unit)}</title></circle>')
    out.append("</svg></div>")
    keys = "".join(f'<li><i style="background:{c}"></i>{esc(nm)}</li>' for nm, c, _ in series)
    return "".join(out) + f'<ul class="keys">{keys}<li class="hint">dashed: across days without use</li></ul>'




def svg_bars(rows, unit_h=True):
    """Stacked bars of engine time per bucket (idle / working / full / overspeed)."""
    W, H, L, B = 760, 260, 44, 28
    peak = max([sum(t[k] for k in BAND_COLORS) for _, t in rows] + [1]) / 3600
    step = 1 if peak <= 6 else 2 if peak <= 12 else 5 if peak <= 30 else 10 if peak <= 60 else 50
    top = max(step, (int(peak / step) + 1) * step)
    n = max(len(rows), 1)
    bw = (W - L - 10) / n
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Engine hours by throttle band">']
    for v in range(0, int(top) + 1, step):
        y = H - B - (H - B - 10) * v / top
        parts.append(f'<line x1="{L}" x2="{W - 6}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{L - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{v} h</text>')
    every = max(1, n // 16)
    for i, (label, t) in enumerate(rows):
        x = L + i * bw + bw * 0.15
        y = H - B
        tip = [label] + [f"{BAND_NAMES[k]} {hm(t[k])}" for k in BAND_COLORS if t[k]]
        parts.append(f'<g><title>{esc(" | ".join(tip))}</title>')
        for k, col in BAND_COLORS.items():
            h = (H - B - 10) * t[k] / 3600 / top
            if h > 0:
                y -= h
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw * 0.7:.1f}" height="{h:.1f}" fill="{col}"/>')
        parts.append("</g>")
        if i % every == 0:
            parts.append(f'<text x="{x + bw * 0.35:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_hist(hist, bands, max_rpm=3500):
    """Time spent at each engine speed, coloured by band."""
    W, H, L, B = 760, 220, 44, 28
    size = bands.get("bin", 250)
    bins = list(range(0, int(max_rpm) + size, size))
    vals = [hist.get(str(b), 0) / 3600 for b in bins]
    peak = max(vals + [0.01])
    bw = (W - L - 10) / len(bins)
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Time at each engine speed">']
    for frac in (0.5, 1.0):
        y = H - B - (H - B - 10) * frac
        parts.append(f'<line x1="{L}" x2="{W - 6}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{L - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{peak * frac:.1f} h</text>')
    for i, (b, v) in enumerate(zip(bins, vals)):
        mid = b + size / 2
        k = "over_s" if mid > bands.get("over_at", 3050) else "full_s" if b >= bands.get("full_at", 2600) else \
            "work_s" if b >= bands.get("idle_below", 1400) else "idle_s"
        h = (H - B - 10) * v / peak
        x = L + i * bw
        parts.append(f'<g><title>{b}-{b + size - 1} rpm: {hm(v * 3600)}</title>'
                     f'<rect x="{x + 1:.1f}" y="{H - B - h:.1f}" width="{bw - 2:.1f}" height="{max(h, 0):.1f}" fill="{BAND_COLORS[k]}"/></g>')
        if b % 500 == 0:
            parts.append(f'<text x="{x:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{b}</text>')
    parts.append("</svg>")
    return "".join(parts)


def band_strip(t):
    """One long bar split by band, with the percentages under it."""
    run = sum(t[k] for k in BAND_COLORS) or 1
    segs = "".join(f'<span style="flex:{t[k] / run:.4f};background:{c}" title="{BAND_NAMES[k]}"></span>'
                   for k, c in BAND_COLORS.items() if t[k])
    keys = "".join(f'<li><i style="background:{c}"></i>{BAND_NAMES[k]} <b>{pct(t[k], run)}</b> '
                   f'<small>{hm(t[k])}</small></li>' for k, c in BAND_COLORS.items())
    return f'<div class="strip">{segs or "<span style=flex:1></span>"}</div><ul class="keys">{keys}</ul>'


# ---------------------------------------------------------------- the report page

def card(label, value, note="", tone="", href=None):
    tag = f'a href="{href}"' if href else "div"
    return (f'<{tag} class="card {tone}{" link" if href else ""}"><div class="lbl">{esc(label)}</div>'
            f'<div class="val">{value}</div><div class="note">{note}</div></{tag.split()[0]}>')


PER_PAGE = 10
PAGE_SIZES = (10, 20, 50, 100)
# Day-by-day paging in the browser: Newer / Older and the page size swap rows in place, and the page scrolls by
# however much the table grew or shrank, so the button you pressed stays under your finger.
DAYS_JS = """<script>(function(){document.querySelectorAll('section.days:not([data-ok])').forEach(function(sec){
sec.dataset.ok=1;var rows=[].slice.call(sec.querySelectorAll('tr.dr')),size=10,page=0;
try{size=+localStorage.getItem('bobcatDaysPerPage')||10}catch(e){}
function draw(){var pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);
rows.forEach(function(r,i){r.hidden=!(i>=page*size&&i<(page+1)*size)});
sec.querySelectorAll('.pg-info').forEach(function(e){e.textContent='Page '+(page+1)+' of '+pages+' \u00b7 '+rows.length+' days'});
sec.querySelectorAll('[data-go=newer]').forEach(function(b){b.disabled=page==0});
sec.querySelectorAll('[data-go=older]').forEach(function(b){b.disabled=page>=pages-1});
sec.querySelectorAll('select').forEach(function(s){s.value=size})}
function keep(el,fn){var y=el.getBoundingClientRect().top;fn();window.scrollBy(0,el.getBoundingClientRect().top-y)}
sec.addEventListener('click',function(e){var b=e.target.closest('[data-go]');if(!b||b.disabled)return;
keep(b,function(){page+=b.dataset.go=='older'?1:-1;draw()})});
sec.addEventListener('change',function(e){var s=e.target;if(s.tagName!='SELECT')return;keep(s,function(){
var first=page*size;size=+s.value;page=Math.floor(first/size);try{localStorage.setItem('bobcatDaysPerPage',size)}catch(x){}draw()})});
draw()})})();</script>"""


def report_body(days, bands, events, period, units="F", today=None, max_rpm=3500, links=True, page=1):
    keys = select(days, period, today)
    t = total([days[k] for k in keys])
    if period == "all":
        evs = list(events)
    else:
        today = today or datetime.date.today()
        first = (today - datetime.timedelta(days=int(period) - 1)).isoformat()
        evs = [e for e in events if first <= day_of(e.get("t")) <= today.isoformat()]
    alarms = sum(1 for e in evs if e.get("level") == "alarm")
    warns = len(evs) - alarms
    used = [k for k in keys if days[k].get("run_s", 0) > 60 and k != "no-date"]
    failed = max(0, t["cranks"] - t["starts"])
    out = []
    if links:
        out.append('<nav class="periods">' + "".join(
            f'<a href="?p={p}" class="{"on" if p == period else ""}">{n}</a>' for p, n in PERIODS) + "</nav>")
    if not keys or not t["key_s"]:
        out.append('<p class="empty">Nothing recorded in this period yet. The dash records usage while the key is on.</p>')
        return "".join(out)
    hours = (f'{days[keys[-1]].get("h1", 0) - days[keys[0]].get("h0", 0):.1f} on the meter'
             if days[keys[0]].get("h0") is not None and days[keys[-1]].get("h1") is not None else "")
    out.append('<section class="cards">')
    run = t["run_s"] or 1
    out.append(card("Engine running", hm(t["run_s"]), (hours + ", " if hours else "") + f'key on {hm(t["key_s"])}'))
    out.append(card("Full throttle", pct(t["full_s"] + t["over_s"], t["run_s"]),
                    f'{hm(t["full_s"] + t["over_s"])}: normal working', "good"))
    out.append(card("Part throttle", pct(t["work_s"], t["run_s"]),
                    f'{hm(t["work_s"])}: cold warm-up, pump priming, timing',
                    "warn" if t["work_s"] / run > PART_WARN else ""))
    out.append(card("Idle", pct(t["idle_s"], t["run_s"]),
                    f'{hm(t["idle_s"])} below {bands["idle_below"]} rpm: warm-up, cool-down',
                    "warn" if t["idle_s"] / run > 0.4 else ""))
    out.append(card("Days used", str(len(used)), f'avg {hm(t["run_s"] / len(used))} a day' if used else ""))
    out.append(card("Starts", str(t["starts"]),
                    f'{failed} crank{"s" if failed != 1 else ""} that didn\'t start, {t["crank_s"]:.0f} s on the starter',
                    "warn" if failed > max(2, t["starts"] // 4) else ""))
    out.append(card("Hot shutdowns", str(t["hot_stops"]), f'of {t["stops"]} stops: shut off before the cool-down finished',
                    "warn" if t["hot_stops"] else "good" if t["stops"] else ""))
    out.append(card("Alarms", str(alarms), f"{warns} warnings" + (" - see the list" if links else ""),
                    "bad" if alarms else "good", href="/alarms?all=1" if links else None))
    out.append("</section>")
    out.append('<section class="panel"><h2>Throttle use</h2>' + band_strip(t) +
               '<p class="hint">Work at full throttle: the governor holds the speed. Idle to warm up and cool down. '
               'Part throttle only to warm a cold engine, prime the pump or set the timing.</p></section>')
    rows = buckets(days, period, today)
    if rows:
        out.append(f'<section class="panel"><h2>Engine time by {"day" if period in ("7", "30") else "month"}</h2>'
                   + svg_bars(rows) + "</section>")
    out.append('<section class="panel"><h2>Time at each engine speed (rpm)</h2>' + svg_hist(t["hist"], bands, max_rpm)
               + f'<p class="hint">Idle below {bands["idle_below"]} rpm, part throttle up to {bands["full_at"]} rpm, full throttle from there, '
               f'overspeed above {bands["over_at"]} rpm (settings: [usage] and [tach] in config.toml).</p></section>')
    def at(field, hi=True):
        """The period's highest (or lowest) daily value, and when: (value, 'Oct 12 2026, 3:42 PM')."""
        got = [(days[k][field], k, days[k].get(field + "_t")) for k in keys if days[k].get(field) is not None]
        if not got:
            return None, ""
        v, k, ts = (max if hi else min)(got, key=lambda g: g[0])
        if ts and clock_valid(ts):
            lt = time.localtime(ts)
            return v, time.strftime("%b ", lt) + f"{lt.tm_mday} {lt.tm_year}, " + settings.hhmm(lt)
        return v, ("" if k == "no-date" else datetime.date.fromisoformat(k).strftime("%b %d %Y"))
    def ext(field, hi, fmt):
        v, when_ = at(field, hi)
        if v is None:
            return None
        return f'<b>{fmt(v)}</b>' + (f'<small>{esc(when_)}</small>' if when_ else "")
    deg_fmt, volt_fmt = (lambda v: temp(v, units)), (lambda v: f"{v:.1f} V")
    probes = sorted({k[2:-4] for d in keys for k in days[d] if k.startswith("p_") and k.endswith("_max")},
                    key=settings.probe_label)
    sensors = [("E-Box Temp", "box", deg_fmt)]
    sensors += [(settings.probe_label(n), f"p_{n}", deg_fmt) for n in probes] or [("Outside Temp", "amb", deg_fmt)]
    sensors += [("Pi CPU", "pi", deg_fmt), ("Battery while running", "v_run", volt_fmt)]
    extremes = [(label, ext(f + "_min", False, fmt), ext(f + "_max", True, fmt)) for label, f, fmt in sensors]
    extremes = [x for x in extremes if x[1] or x[2]]
    by_day = daily(days, period, today)
    dates = [d for d, _ in by_day]
    deg = f"°{units}"
    temps = [(name, col, [temp_val(r.get(k), units) for _, r in by_day]) for name, col, k in
             (("E-box max", "var(--l-ebox)", "box_max"), ("Outside high", "var(--l-hot)", "amb_max"),
              ("Outside low", "var(--l-cold)", "amb_min"), ("Pi CPU max", "var(--l-pi)", "pi_max"))]
    temps = [x for x in temps if any(v is not None for v in x[2])]
    batt = [(name, col, [r.get(k) for _, r in by_day]) for name, col, k in
            (("Lowest while running", "var(--l-cold)", "v_run_min"), ("Highest while running", "var(--l-hot)", "v_run_max"))]
    out.append('<section class="panel"><h2>Temperatures and battery</h2>'
               '<h3>Temperatures by day</h3>' + (svg_lines(dates, temps, deg, "Temperatures by day") if temps else
                                                 '<p class="hint">No temperatures recorded in this period.</p>') +
               '<h3>Battery while running, by day</h3>' + (svg_lines(dates, batt, " V", "Battery voltage by day", 1)
                                                         if any(v is not None for _, _, vs in batt for v in vs) else
                                                         '<p class="hint">The engine didn\'t run in this period.</p>') +
               '<h3>Extremes</h3>' + ('<table class="ext"><tr><th></th><th>Lowest</th><th>Highest</th></tr>' + "".join(
                   f'<tr><th scope="row">{esc(a)}</th><td>{lo or "-"}</td><td>{hi or "-"}</td></tr>' for a, lo, hi in extremes)
                   + "</table>" if extremes else '<p class="hint">No readings in this period.</p>') + "</section>")
    top = {}
    for e in evs:
        top.setdefault(e["what"], [0, 0])[0 if e.get("level") == "alarm" else 1] += 1
    if top:
        out.append('<section class="panel"><h2>Alarms and warnings</h2><table><tr><th>What</th><th>Alarms</th>'
                   '<th>Warnings</th></tr>' + "".join(
                       f"<tr><td>{esc(w)}</td><td>{a}</td><td>{n}</td></tr>"
                       for w, (a, n) in sorted(top.items(), key=lambda x: (-x[1][0], -x[1][1]))) + "</table></section>")
    shown = [k for k in reversed(keys) if days[k].get("key_s")]
    pager = ""
    paged = links and len(shown) > min(PAGE_SIZES)
    if paged:      # paged in the browser (DAYS_JS): no reload, the screen doesn't move
        opts = "".join(f'<option value="{n}"{" selected" if n == PER_PAGE else ""}>{n}</option>' for n in PAGE_SIZES)
        pager = ('<div class="pager"><button class="btn gray" type="button" data-go="newer">&larr; Newer</button>'
                 f'<span class="pg-info">{len(shown)} days</span>'
                 f'<label>Show <select aria-label="Days per page">{opts}</select> a page</label>'
                 '<button class="btn gray" type="button" data-go="older">Older &rarr;</button></div>')
    out.append('<section class="panel days" id="days"><h2>Day by day</h2>' + pager + '<div class="scroll"><table><tr><th>Day</th><th>Engine</th>'
               '<th>Full</th><th>Part</th><th>Idle</th><th>Key on</th><th>Starts</th><th>Hot stops</th>'
               '<th>E-box max</th><th>Outside</th><th>Meter</th></tr>')
    for i, k in enumerate(shown):
        r = days[k]
        meter = f'{r["h1"]:.1f} h' if r.get("h1") is not None else ""
        outside = f'{temp(r.get("amb_min"), units)} - {temp(r.get("amb_max"), units)}' if r.get("amb_max") is not None else "-"
        tr = '<tr class="dr"' + (" hidden" if paged and i >= PER_PAGE else "") + ">"
        out.append(f'{tr}<td>{k}</td><td>{hm(r.get("run_s"))}</td>'
                   f'<td>{pct(r.get("full_s", 0) + r.get("over_s", 0), r.get("run_s"))}</td>'
                   f'<td{" class=part" if r.get("run_s") and r.get("work_s", 0) / r["run_s"] > PART_WARN else ""}>'
                   f'{pct(r.get("work_s", 0), r.get("run_s"))}</td>'
                   f'<td>{pct(r.get("idle_s", 0), r.get("run_s"))}</td><td>{hm(r.get("key_s"))}</td>'
                   f'<td>{r.get("starts", 0)}</td><td>{r.get("hot_stops", 0)}</td><td>{temp(r.get("box_max"), units)}</td>'
                   f'<td>{outside}</td><td>{meter}</td></tr>')
    out.append("</table></div>" + pager + "</section>" + (DAYS_JS if paged else ""))
    return "".join(out)


CSS = """
:root{--bg:#f3f4f6;--panel:#fff;--ink:#14181f;--dim:#5b6472;--line:#dde1e7;--accent:#1f6feb;--hdr:#0b0e13;--hdr-ink:#eceff4;
--hdr-dim:#98a2b1;--on-color:#fff;--idle:#8b95a5;--part:#d99a00;--full:#2f9e5b;--l-ebox:#c27c00;--l-hot:#d93a3a;--l-cold:#1f6feb;--l-pi:#8250df;--over:#d93a3a;--good:#2f9e5b;--warn:#c27c00;
--bad:#d93a3a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "B612",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--hdr);color:var(--hdr-ink);padding:12px max(16px,env(safe-area-inset-right,0px)) 12px max(16px,env(safe-area-inset-left,0px));
display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center}
header b{font-size:18px;letter-spacing:.06em}header .ver{color:var(--hdr-dim);font-size:14px}
header nav{display:flex;gap:4px;flex-wrap:wrap}header nav a{color:var(--hdr-dim);text-decoration:none;padding:6px 12px;border-radius:8px}
header nav a.on{background:var(--hdr-ink);color:var(--hdr)}
main{max-width:1100px;margin:0 auto;padding-block:16px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1{font-size:24px;margin:8px 0 14px;text-wrap:balance}h2{font-size:15px;margin:0 0 12px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 0 14px;min-width:0}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0 0 14px}@media (min-width:860px){.cards{grid-template-columns:repeat(4,minmax(0,1fr))}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;border-left:5px solid var(--line);min-width:0;min-height:118px;display:flex;flex-direction:column}
.card .lbl{color:var(--dim);font-size:14px}.card .val{font-size:clamp(17px,4.6vw,24px);line-height:1.15;font-weight:700;margin:2px 0;font-variant-numeric:tabular-nums;overflow-wrap:normal;word-break:keep-all}.card .note{margin-top:auto}.card .note{color:var(--dim);font-size:13px}
a.card.link{color:var(--ink);text-decoration:none}a.card.link:hover{border-color:var(--accent)}
.pager{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 0;color:var(--dim);flex-wrap:wrap}.pager select{font:inherit;padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink)}html{overflow-anchor:none}
.card.good{border-left-color:var(--good)}.card.warn{border-left-color:var(--warn)}.card.bad{border-left-color:var(--bad)}
.periods{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}.periods a{padding:7px 14px;border:1px solid var(--line);border-radius:20px;color:var(--ink);text-decoration:none;background:var(--panel)}
.periods a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.strip{display:flex;height:28px;border-radius:8px;overflow:hidden;background:var(--line)}
.keys{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-wrap:wrap;gap:6px 22px}.keys i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}
.keys small{color:var(--dim)}
.chart{width:100%;height:auto;display:block}.chartwrap{overflow-x:auto}.chart.lines{min-width:600px}.chart .grid{stroke:var(--line)}.chart .ax{fill:var(--dim);font-size:12px}
td.part{color:var(--warn);font-weight:700}h3{font-size:14px;color:var(--dim);font-weight:600;margin:14px 0 6px}h3:first-of-type{margin-top:0}.hint{color:var(--dim);font-size:13px;margin:8px 0 0}.empty{color:var(--dim);font-size:18px;padding:30px 0}
table{border-collapse:collapse;width:100%;font-size:15px;font-variant-numeric:tabular-nums}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
td small.hint{white-space:normal;display:block;max-width:46ch}
th{color:var(--dim);font-weight:600}.scroll{overflow-x:auto}
table.ext{width:auto;margin:4px auto 0;font-size:16px}table.ext th,table.ext td{text-align:center;white-space:normal;padding:9px 18px;vertical-align:top}
table.ext th[scope=row]{text-align:right;color:var(--dim);font-weight:400}table.ext td small{display:block;color:var(--dim);font-size:13px;margin-top:2px}
table.ext tr:last-child>*{border-bottom:0}@media (max-width:600px){table.ext th,table.ext td{padding:8px 6px}}
dl.pairs{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0}dd small{color:var(--dim);font-weight:400}@media (max-width:600px){dd small{display:block}}dt{color:var(--dim)}dd{margin:0;font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}@media (min-width:860px){.tiles{grid-template-columns:repeat(4,minmax(0,1fr))}}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;border-top:5px solid var(--good);min-height:92px;display:flex;flex-direction:column;justify-content:space-between;min-width:0}
.tile.warn{border-top-color:var(--warn)}.tile.alarm{border-top-color:var(--bad)}.tile.unknown,.tile.idle{border-top-color:var(--idle)}
.tile .lbl{color:var(--dim);font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile .val{font-size:clamp(17px,4.6vw,25px);line-height:1.15;font-weight:700;font-variant-numeric:tabular-nums;overflow-wrap:normal;word-break:keep-all;margin:2px 0}.you{color:var(--dim);font-size:14px;margin:0 0 10px}a.tile.link{color:var(--ink);text-decoration:none}a.tile.link:hover{border-color:var(--accent)}tr:target td{background:var(--line)}tr:target td:first-child{box-shadow:inset 4px 0 var(--accent)}tr[id]{scroll-margin-top:16px}.tile .note{color:var(--dim);font-size:12px;line-height:1.3;min-height:1.3em;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.pill{display:inline-block;padding:2px 10px;border-radius:12px;font-size:13px;font-weight:600;color:var(--on-color)}
.pill.alarm,.pill.due{background:var(--bad)}.pill.warn,.pill.soon{background:var(--warn)}.pill.ok{background:var(--good)}.pill.unknown{background:var(--idle)}
.btn{display:inline-block;padding:10px 18px;border-radius:10px;border:0;background:var(--accent);color:var(--on-color);font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.btn.gray{background:var(--idle)}.btn.red{background:var(--bad)}.btn:disabled{opacity:.5;cursor:default}
.list a{display:flex;justify-content:space-between;gap:12px;padding:11px 4px;border-bottom:1px solid var(--line);color:var(--ink);text-decoration:none}
.list a small{color:var(--dim)}.msg{padding:12px 14px;border-radius:10px;margin:10px 0;background:var(--line)}
.msg.bad{background:var(--bad);color:var(--on-color)}.msg.good{background:var(--good);color:var(--on-color)}
footer{color:var(--dim);font-size:13px;text-align:center;padding:10px 16px 24px}
header .theme{margin-left:auto;font:inherit;font-size:13px;padding:5px 12px;border-radius:6px;cursor:pointer;background:transparent;
color:var(--hdr-ink);border:1px solid var(--hdr-dim)}
"""

# Dark = the Airbus ECAM look: black, cyan labels, green normal values, amber caution, red warning, white
# underlined titles, square corners. Used when the device is in dark mode, or when Dark is picked (theme switch).
ECAM = """
:root{--bg:#000;--panel:#0b0d10;--ink:#f2f4f5;--dim:#3fd0e6;--line:#2a3036;--accent:#3fd0e6;--hdr:#000;--hdr-ink:#f2f4f5;
--hdr-dim:#3fd0e6;--on-color:#000;--idle:#7d868f;--part:#ffad1f;--full:#3ee36a;--over:#ff3b30;--good:#3ee36a;--warn:#ffad1f;
--bad:#ff3b30;--l-ebox:#ffad1f;--l-hot:#ff5ad9;--l-cold:#3fd0e6;--l-pi:#f2f4f5;--val:#3ee36a;--note:#a9b1b9;color-scheme:dark}
header{border-bottom:2px solid var(--line)}
header nav a{border-radius:3px;border:1px solid transparent}
header nav a.on{background:transparent;color:var(--accent);border-color:var(--accent)}
header .theme{border-radius:3px}
h2{color:var(--ink);text-decoration:underline;text-underline-offset:5px;text-decoration-thickness:2px}
.panel,.card,.tile{border-radius:4px}
.card .val,.tile .val,dd,table.ext b,td{color:var(--val)}
.card.warn .val,.tile.warn .val,td.part{color:var(--warn)}
.card.bad .val,.tile.alarm .val{color:var(--bad)}
.tile.unknown .val,.tile.idle .val{color:var(--note)}
td small,.hint,.card .note,.tile .note,.keys small,footer,table.ext td small,.you,.list a small,dd small{color:var(--note)}
.periods a{border-radius:3px}
.periods a.on{background:transparent;color:var(--accent);border-color:var(--accent)}
.btn{border-radius:3px;background:transparent;color:var(--accent);border:1px solid var(--accent)}
.btn.gray{background:transparent;color:var(--note);border-color:var(--note)}
.btn.red{background:transparent;color:var(--bad);border-color:var(--bad)}
.strip{border-radius:2px}
"""


def _scoped(rules, root):
    """ECAM's rules for one way of choosing dark: ':root' becomes root, every other selector goes under it."""
    out = []
    for rule in rules.strip().replace("\n", "").split("}"):
        if rule.strip():
            sel, body = rule.split("{", 1)
            out.append(",".join(root if x.strip() == ":root" else f"{root} {x.strip()}" for x in sel.split(","))
                       + "{" + body + "}")
    return "".join(out)


CSS += ('@media (prefers-color-scheme:dark){' + _scoped(ECAM, ':root:not([data-theme="light"])') + "}"
        + _scoped(ECAM, ':root[data-theme="dark"]'))

# Light / Dark, remembered by each phone or laptop (its own browser storage); nothing picked = the device's setting.
THEME_HEAD = ("<script>try{var t=localStorage.getItem('moss-theme');if(t==='light'||t==='dark')"
              "document.documentElement.dataset.theme=t}catch(e){}</script>")
THEME_JS = """<script>
function mossDark(){var t=document.documentElement.dataset.theme;return t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches}
function mossTheme(t){if(!t)t=mossDark()?'light':'dark';
if(t==='auto'){delete document.documentElement.dataset.theme}else{document.documentElement.dataset.theme=t}
try{if(t==='auto')localStorage.removeItem('moss-theme');else localStorage.setItem('moss-theme',t)}catch(e){}mossThemeShow()}
function mossThemeShow(){var b=document.getElementById('theme');if(b)b.textContent=mossDark()?'LIGHT':'DARK';
var c;try{c=localStorage.getItem('moss-theme')||'auto'}catch(e){c='auto'}
document.querySelectorAll('[data-pick]').forEach(function(x){x.classList.toggle('gray',x.dataset.pick!==c)})}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',mossThemeShow);mossThemeShow();
</script>"""


FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONTS = (("B612-Regular.ttf", 400), ("B612-Bold.ttf", 700))


def font_css(embed=False):
    """@font-face for B612 (fonts/, SIL OFL): served by the dash at /fonts/..., or inside the file for a
    stand-alone report (a USB stick copy opens the same on any computer)."""
    import base64
    out = []
    for name, weight in FONTS:
        path = os.path.join(FONT_DIR, name)
        if not os.path.isfile(path):
            continue
        if embed:
            with open(path, "rb") as f:
                src = "data:font/ttf;base64," + base64.b64encode(f.read()).decode()
        else:
            src = "/fonts/" + name
        out.append(f"@font-face{{font-family:'B612';src:url('{src}') format('truetype');font-weight:{weight};"
                   f"font-style:normal;font-display:swap}}")
    return "".join(out)


def page(title, body, nav=None, active="", version="", foot="", embed_fonts=False):
    """A whole HTML page. nav: [(href, name)] for the top bar, or None for a stand-alone file."""
    links = ""
    if nav:
        links = "<nav>" + "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{n}</a>' for h, n in nav) + "</nav>"
    switch = ('<button class="theme" id="theme" onclick="mossTheme()" title="Switch between light and dark">DARK</button>'
              if nav else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{esc(title)} - M.O.S.S.</title>{THEME_HEAD}'
            f"<style>{font_css(embed_fonts)}{CSS}</style></head><body><header><b>M.O.S.S.</b><span class='ver'>Bobcat M700</span>"
            f'<span class="ver">{esc(version)}</span>{links}{switch}</header><main><h1>{esc(title)}</h1>{body}</main>'
            f"<footer>{foot}</footer>{THEME_JS}</body></html>")


# ---------------------------------------------------------------- exports

def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def when(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t and clock_valid(t) else ""


def usage_csv(days):
    head = ["date", "engine_h", "idle_h", "part_throttle_h", "full_h", "overspeed_h", "key_on_h", "starts", "cranks",
            "crank_s", "stops", "hot_stops", "meter_start_h", "meter_end_h", "box_max_c", "outside_min_c",
            "outside_max_c", "pi_max_c", "batt_run_min_v", "batt_run_max_v", "e_box_max_at", "outside_min_at",
            "outside_max_at", "pi_max_at", "batt_run_min_at", "batt_run_max_at"]
    rows = []
    for k in sorted(days):
        r = days[k]
        rows.append([k] + [round(r.get(f, 0) / 3600, 3) for f in ("run_s", "idle_s", "work_s", "full_s", "over_s", "key_s")]
                    + [r.get(f, 0) for f in ("starts", "cranks")] + [round(r.get("crank_s", 0), 1)]
                    + [r.get(f, 0) for f in ("stops", "hot_stops")]
                    + [r.get(f, "") for f in ("h0", "h1", "box_max", "amb_min", "amb_max", "pi_max", "v_run_min", "v_run_max")]
                    + [when(r.get(f + "_t")) for f in ("box_max", "amb_min", "amb_max", "pi_max", "v_run_min", "v_run_max")])
    return _csv(head, rows)


def alarms_csv(events):
    return _csv(["when", "engine_h", "what", "level", "detail", "lasted_s", "cleared_from_list"],
                [[when(e.get("t")), e.get("h"), e.get("what"), e.get("level"), e.get("detail"), e.get("dur_s"),
                  "yes" if e.get("cleared") else ""] for e in events])


def service_csv(service, hours):
    rows = []
    for it, state, left, days in service.status(hours):
        s = service.state.get(it["id"], {})
        rows.append([it["name"], service.interval(it), state, round(left, 1), "" if days is None else round(days),
                     s.get("done_h", ""), when(s.get("done_t")), "install" if s.get("baseline") else ""])
    status = _csv(["item", "every_h", "state", "hours_left", "days_left", "last_done_h", "last_done", "counted_from"], rows)
    done = _csv(["item", "engine_h", "when"], [[h["name"], h["h"], when(h.get("t"))] for h in service.history])
    return status, done


def bundle(ctx):
    """{filename: bytes} of everything worth keeping. ctx: the dash's objects (see web.py)."""
    usage, events, service = ctx["usage"], ctx["events"], ctx["service"]
    days = dict(usage.days)
    evs = list(events.events)
    hours = ctx["hours"]()
    status, done = service_csv(service, hours)
    units = settings.units()
    max_rpm = ctx["cfg"].get("tach", {}).get("max_rpm", 3500)
    stamp = time.strftime("%b %d %Y %H:%M") if clock_valid() else "date not set"
    body = (f'<p class="hint">Exported {stamp} at {hours:.1f} engine hours, software v{esc(ctx["version"])}.</p>'
            + report_body(days, usage.bands(), evs, "all", units, max_rpm=max_rpm, links=False))
    files = {
        "report.html": page("Performance report", body, version=f'v{ctx["version"]}', embed_fonts=True).encode(),
        "usage-daily.csv": usage_csv(days).encode(),
        "alarms.csv": alarms_csv(evs).encode(),
        "service-status.csv": status.encode(),
        "service-done.csv": done.encode(),
    }
    for name in ("usage.json", "events.json", "service.json", "hours_a.json", "hours_b.json", "updates.json"):
        p = os.path.join(ctx["data_dir"], name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                files["data/" + name] = f.read()
    cfg_path = os.path.join(ctx["repo"], "config.toml")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "rb") as f:
            files["config.toml"] = f.read()
    log_text = ctx.get("journal", lambda: "")()
    if log_text:
        files["dash-log.txt"] = log_text.encode()
    files["README.txt"] = (
        "M.O.S.S. (Maintenance, Operations, and Service System) export, Bobcat M700\n\n"
        "report.html         open in any web browser: the performance report (all time)\n"
        "usage-daily.csv     one line per day: engine hours by throttle band, starts, temperatures (opens in Excel)\n"
        "alarms.csv          every alarm and warning recorded\n"
        "service-status.csv  each service item: when it was last done, hours left\n"
        "service-done.csv    service marked done on the dash\n"
        "config.toml         the dash's settings\n"
        "data/               the dash's own files (a backup: copy back into ~/bobcat-dash-data to restore)\n"
        "dash-log.txt        the dash's log (for trouble-shooting)\n").encode()
    return files


def bundle_zip(ctx):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in bundle(ctx).items():
            z.writestr(name, data)
    return buf.getvalue()


def export_name(hours):
    return (time.strftime("%Y-%m-%d_%H%M") if clock_valid() else "no-date") + f"_{hours:.0f}h"


def json_dump(obj):
    return json.dumps(obj, indent=1).encode()
