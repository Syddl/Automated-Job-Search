"""Job board: check jobs.json, apply changes, and write board.html.

  py -X utf8 board.py                       check jobs.json and rebuild board.html
  py -X utf8 board.py apply FILE            add or update jobs from FILE, then rebuild
  py -X utf8 board.py move 12=applied ...   change statuses, then rebuild
  py -X utf8 board.py serve                 rebuild, then serve the board at http://127.0.0.1:8765 so its buttons work

Nothing is saved when a check fails.
"""
import datetime as dt
import html
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
JOBS = HERE / "jobs.json"
FACTS = HERE / "facts.md"
INBOX = HERE / ".hunt" / "inbox.json"
BOARD = HERE / "board.html"

LABELS = {
    "olj": "OnlineJobs.ph", "jobstreet": "JobStreet", "indeed": "Indeed", "linkedin": "LinkedIn",
    "remoteok": "RemoteOK", "wwr": "We Work Remotely", "himalayas": "Himalayas", "remotive": "Remotive",
    "hn": "Hacker News",
}
COLUMNS = [
    ("leads", "Leads"), ("high", "High priority"), ("needs-action", "Needs action"), ("applied", "Applied"),
    ("talking", "Talking"), ("interview", "Interview booked"), ("won", "Won"), ("lost", "Lost"),
]
STATUSES = {key for key, _ in COLUMNS} | {"rejected"}
APP_KEYS = {"subject", "body", "note"}

# The "Do not claim" list in facts.md, as patterns. Matched case-insensitively.
DO_NOT_CLAIM = [
    r"\bRAG\b", r"retrieval[- ]augmented", r"vector (database|db|store)", r"\blangchain\b", r"\bllamaindex\b",
    r"prompt caching", r"tool[- ]calling", r"function calling", r"structured outputs?", r"fine[- ]tun",
    r"built (an? )?mcp", r"mcp servers? i (built|wrote|made)", r"deployed saas", r"saas (is )?(live|in production|deployed)",
    r"real (training )?data", r"\b0\.70\b", r"\b93\s*%", r"\b42 migrations", r"\bn8n\b", r"\bai consultant\b",
    r"\bwayfinder\b",
]
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers(text):
    """Numbers in text, with thousands commas removed: "$1,200 and 0.90" -> {"1200", "0.90"}."""
    return set(NUMBER.findall(re.sub(r"(?<=\d),(?=\d)", "", text or "")))


def check(data, facts):
    """Return a list of problems; empty means jobs.json is safe to save."""
    errors = []
    from_facts = numbers(facts)
    ids, urls = set(), set()
    for job in data["jobs"]:
        tag = f"#{job.get('id')}"
        if not isinstance(job.get("id"), int) or job["id"] in ids:
            errors.append(f"{tag}: id must be a unique integer")
        ids.add(job.get("id"))
        url = job.get("url") or ""
        if not url.startswith(("https://", "http://")) or url in urls:
            errors.append(f"{tag}: url must be a unique http(s) link")
        urls.add(url)
        if job.get("source") not in LABELS:
            errors.append(f"{tag}: unknown source {job.get('source')!r}")
        for field in ("title", "company", "found"):
            if not job.get(field):
                errors.append(f"{tag}: missing {field}")
        status, score = job.get("status"), job.get("score")
        if status not in STATUSES:
            errors.append(f"{tag}: unknown status {status!r}")
        if not ((isinstance(score, int) and 0 <= score <= 100) or (score is None and status == "rejected")):
            errors.append(f"{tag}: score must be 0-100 (null only when rejected)")
        if not isinstance(job.get("history"), list):
            errors.append(f"{tag}: history must be a list")
        app = job.get("application")
        if status == "high" and not app:
            errors.append(f"{tag}: high priority needs an application")
        if not app:
            continue
        if not isinstance(app, dict) or not set(app) <= APP_KEYS or not any(app.values()):
            errors.append(f"{tag}: application needs subject, body or note text only")
            continue
        if len(app.get("note") or "") > 300:
            errors.append(f"{tag}: LinkedIn note is over 300 characters")
        text = "\n".join(str(value) for value in app.values() if value)
        allowed = from_facts | numbers(" ".join(str(job.get(k) or "") for k in ("title", "company", "pay", "post")))
        for number in sorted(numbers(text) - allowed):
            errors.append(f"{tag}: number {number} is not in facts.md or the post")
        for pattern in DO_NOT_CLAIM:
            hit = re.search(pattern, text, re.I)
            if hit:
                errors.append(f"{tag}: {hit.group(0)!r} is on the Do not claim list")
    return errors


def apply_changes(data, changes, inbox, stamp):
    """Add jobs without an id (an "inbox": n entry pulls that feed item's fields) and update jobs with one.

    stamp is "YYYY-MM-DD HH:MM". Returns notes for the user. Mutates data.
    """
    today = stamp[:10]
    by_id = {job["id"]: job for job in data["jobs"]}
    urls = {job["url"] for job in data["jobs"]}
    feed = {item["n"]: item for item in inbox}
    notes = []
    for change in changes.get("jobs", []):
        change = dict(change)
        if "id" in change:
            job = by_id.get(change["id"])
            if job is None:
                raise SystemExit(f"No job #{change['id']}. Nothing saved.")
            if "status" in change and change["status"] != job["status"]:
                job["history"].append({"date": today, "status": change["status"]})
            job.update(change)
            continue
        if "inbox" in change:
            n = change.pop("inbox")
            if n not in feed:
                raise SystemExit(f"No inbox item {n}. Nothing saved.")
            change = {**{k: v for k, v in feed[n].items() if k != "n"}, **change}
        if change.get("url") in urls:
            notes.append(f"skipped duplicate {change.get('url')}")
            continue
        job = {
            "id": max(by_id, default=0) + 1, "found": today, "pay": None, "posted": None, "post": None,
            "score": None, "why": None, "flags": [], "reason": None, "application": None, "apply_points": None,
            **change,
        }
        job["history"] = [{"date": today, "status": job.get("status")}]
        if job.get("status") == "rejected":
            job["post"] = None  # rejected jobs keep no post text, so jobs.json stays small
        data["jobs"].append(job)
        by_id[job["id"]] = job
        urls.add(job["url"])
    if "run" in changes:
        data["last_run"] = {"at": stamp, "failed_sources": changes["run"].get("failed_sources", [])}
    return notes


def move(data, pairs, stamp):
    """pairs like ["12=applied", "9=talking"]."""
    jobs = [{"id": int(job_id), "status": status} for job_id, _, status in (p.partition("=") for p in pairs)]
    return apply_changes(data, {"jobs": jobs}, [], stamp)


# ---------- page ----------

DOTS = {"olj": "#3b82f6", "jobstreet": "#ec4899", "indeed": "#6366f1", "linkedin": "#0ea5e9", "remoteok": "#f59e0b",
        "wwr": "#10b981", "himalayas": "#8b5cf6", "remotive": "#14b8a6", "hn": "#f97316"}
STAGE = {"leads": "var(--muted)", "high": "var(--green)", "needs-action": "var(--red)", "applied": "var(--blue)",
         "talking": "var(--violet)", "interview": "var(--teal)", "won": "var(--green)", "lost": "var(--muted)"}
PIPELINE = ["leads", "applied", "talking", "interview", "won", "lost"]


def esc(value):
    return "" if value is None else html.escape(str(value))


def short(day):
    d = dt.date.fromisoformat(day)
    return f"{d:%b} {d.day}"


def badge(job, size=""):
    s = job.get("score") or 0
    tone = "strong" if s >= 85 else "good" if s >= 70 else "ok" if s >= 50 else "low"
    return f'<span class="score s-{tone} {size}" title="Fit score out of 100">{s}</span>'


def site(job):
    return f'<span class="src" style="--dot:{DOTS[job["source"]]}">{LABELS[job["source"]]}</span>'


def chips(job, today):
    flags = list(job.get("flags") or [])
    if job["status"] == "applied":
        applied = next((h["date"] for h in reversed(job["history"]) if h["status"] == "applied"), None)
        days = applied and (today - dt.date.fromisoformat(applied)).days
        if days and days >= 7:
            flags.append(f"follow up? applied {days} days ago")
    if job.get("apply_points") and job["status"] == "high":
        flags.append(f"Spend {job['apply_points']} Apply Points")
    return "".join(f'<span class="chip warn">{esc(flag)}</span>' for flag in flags)


def meta(job):
    bits = [esc(job["company"]), esc(job.get("pay")), job.get("posted") and f"posted {short(job['posted'])}"]
    return " · ".join(bit for bit in bits if bit)


def why(job):
    return f'<p class="why">{esc(job["why"])}</p>' if job.get("why") else ""


def open_link(job, kind="btn primary"):
    return f'<a class="{kind}" href="{esc(job["url"])}" target="_blank" rel="noopener noreferrer">Open job ↗</a>'


def applied_button(job):
    return f'<button type="button" class="btn" data-move="{job["id"]}" data-status="applied">Mark applied</button>'


def remove_button(job, kind="btn", label="Remove"):
    # Rejected, not deleted: the link stays in jobs.json, so /hunt never adds the job again.
    return (f'<button type="button" class="{kind}" data-move="{job["id"]}" data-status="rejected" '
            f'title="Not a fit: hide it from the board" aria-label="Remove #{job["id"]}">{label}</button>')


def fields(job):
    app = job.get("application") or {}
    out = []
    for key, label, rows in (("subject", "Subject", 2), ("body", "Message", 12), ("note", "LinkedIn note", 4)):
        if app.get(key):
            words = f'<span class="muted">{len(app[key].split())} words</span>' if key == "body" else ""
            box = f"app-{job['id']}-{key}"
            out.append(f'<div class="field"><div class="fhead"><span>{label}</span>{words}'
                       f'<button type="button" class="btn sm" data-copy="{box}">Copy</button></div>'
                       f'<textarea id="{box}" rows="{rows}">{esc(app[key])}</textarea></div>')
    return "".join(out)


def ready(job, today):
    return (f'<article class="wide"><div class="info"><div class="row">{badge(job, "lg")}{site(job)}'
            f'<span class="id">#{job["id"]}</span></div><h3>{esc(job["title"])}</h3><p class="meta">{meta(job)}</p>'
            f'{why(job)}{chips(job, today)}'
            f'<ol class="steps"><li>Open the job</li><li>Paste the message and submit</li>'
            f'<li>Click "Mark applied"</li></ol><p class="go">{open_link(job)} {applied_button(job)} {remove_button(job)}</p></div>'
            f'<div class="letter">{fields(job)}</div></article>')


def needs(job, today):
    reason = f'<p class="reason">{esc(job["reason"])}</p>' if job.get("reason") else ""
    return (f'<article class="needs">{badge(job)}<div class="grow"><h3>{esc(job["title"])}</h3>'
            f'<p class="meta">{meta(job)} · {site(job)} · #{job["id"]}</p>{chips(job, today)}{reason}</div>'
            f'{open_link(job, "btn")}{applied_button(job)}{remove_button(job)}</article>')


def mini(job, today):
    remove = remove_button(job, "x", "×") if job["status"] == "leads" else ""  # later stages use "lost"
    return (f'<div class="mini"><a href="{esc(job["url"])}" target="_blank" rel="noopener noreferrer" title="{esc(job.get("why"))}">'
            f'{badge(job)}<span class="t">{esc(job["title"])}</span>'
            f'<span class="muted">{esc(job["company"])} · {LABELS[job["source"]]} · #{job["id"]}</span>{chips(job, today)}</a>'
            f'{remove}</div>')


def render(data, today):
    jobs = sorted(data["jobs"], key=lambda job: -(job.get("score") or 0))
    by_status = {key: [job for job in jobs if job["status"] == key] for key, _ in COLUMNS}
    labels = dict(COLUMNS)
    pills = "".join(f'<span class="pill" style="--stage:{STAGE[key]}"><i></i>{label} <b>{len(by_status[key])}</b></span>'
                    for key, label in COLUMNS if by_status[key])
    run = data.get("last_run") or {}
    failed = ", ".join(run.get("failed_sources") or [])
    failed = f' · <span class="warnText">Failed: {esc(failed)}</span>' if failed else ""
    rejected = sum(job["status"] == "rejected" for job in data["jobs"])
    high = "".join(ready(job, today) for job in by_status["high"]) or '<p class="empty">Nothing ready. Run /hunt in Claude Code.</p>'
    attention = "".join(needs(job, today) for job in by_status["needs-action"]) or '<p class="empty">Nothing needs you.</p>'
    lanes = "".join(
        f'<div class="lane" style="--stage:{STAGE[key]}"><h4><i></i>{labels[key]}<b>{len(by_status[key])}</b></h4>'
        f'{"".join(mini(job, today) for job in by_status[key]) or "<p class=none>Nothing yet</p>"}</div>'
        for key in PIPELINE
    )
    body = (
        f'<header class="top"><div><h1>Job board</h1><p class="sub">Last run {esc(run.get("at") or "never")}{failed}'
        f' · {rejected} rejected</p></div><div class="pills">{pills}</div></header><main class="today">'
        f'<section class="block" style="--stage:var(--green)"><div class="bhead"><h2>Ready to apply</h2>'
        f'<span class="count">{len(by_status["high"])}</span><span class="hint">Highest score first</span></div>{high}</section>'
        f'<section class="block" style="--stage:var(--red)"><div class="bhead"><h2>Needs you</h2>'
        f'<span class="count">{len(by_status["needs-action"])}</span></div>{attention}</section>'
        f'<section class="block"><div class="bhead"><h2>Pipeline</h2></div><div class="pipeline">{lanes}</div></section></main>'
    )
    return Template(PAGE).substitute(body=body)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job board</title>
<style>
:root { --bg:#0e1014; --panel:#14171d; --card:#191d25; --line:#252b36; --text:#e8ebf1; --soft:#b8bfcc; --muted:#7f8899;
  --chip:#222835; --accent:#5b8cff; --green:#3fbf8f; --blue:#5b8cff; --amber:#e5a93d; --red:#f26d6d; --violet:#a78bfa; --teal:#2dd4bf;
  color-scheme: dark; }
@media (prefers-color-scheme: light) { :root { --bg:#f4f5f7; --panel:#ffffff; --card:#ffffff; --line:#e2e5ea; --text:#161a22;
  --soft:#3b4250; --muted:#6b7385; --chip:#eef0f4; --accent:#2f6bff; --green:#0f8a5f; --blue:#2f6bff; --amber:#a5670a;
  --red:#cc3b3b; --violet:#6d4fd8; --teal:#0f8f80; color-scheme: light; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
h1 { font-size: 20px; margin: 0; letter-spacing: -.01em; }
h2, h3, h4 { margin: 0; }
.top { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; justify-content: space-between; padding: 18px 24px;
  border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; }
.sub { margin: 2px 0 0; color: var(--muted); font-size: 13px; }
.warnText { color: var(--amber); }
.pills { display: flex; flex-wrap: wrap; gap: 6px; }
.pill { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; background: var(--chip); font-size: 12px; color: var(--soft); }
.pill i { width: 7px; height: 7px; border-radius: 50%; background: var(--stage); }
.pill b { color: var(--text); }
.score { display: inline-grid; place-items: center; min-width: 34px; height: 24px; padding: 0 6px; border-radius: 6px;
  font-weight: 700; font-size: 13px; font-variant-numeric: tabular-nums; }
.score.lg { min-width: 46px; height: 34px; font-size: 17px; border-radius: 8px; }
.s-strong { background: color-mix(in srgb, var(--green) 18%, transparent); color: var(--green); }
.s-good { background: color-mix(in srgb, var(--blue) 18%, transparent); color: var(--blue); }
.s-ok { background: color-mix(in srgb, var(--amber) 18%, transparent); color: var(--amber); }
.s-low { background: var(--chip); color: var(--muted); }
.src { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--soft); white-space: nowrap; }
.src::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--dot); }
.muted { color: var(--muted); font-size: 12px; }
.meta { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.why { color: var(--soft); margin: 8px 0 0; font-size: 13px; }
.chip { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 6px; margin: 8px 6px 0 0; }
.chip.warn { background: color-mix(in srgb, var(--amber) 15%, transparent); color: var(--amber); }
.reason { margin: 10px 0 0; padding: 8px 10px; border-radius: 8px; font-size: 13px;
  background: color-mix(in srgb, var(--red) 12%, transparent); color: var(--red); }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--chip); color: var(--text); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; white-space: nowrap; }
.btn:hover { border-color: var(--muted); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.sm { padding: 3px 9px; font-size: 12px; margin-left: auto; }
.btn.done { background: var(--green); border-color: var(--green); color: #fff; }
.field { margin-top: 10px; }
.field:first-child { margin-top: 0; }
.fhead { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; color: var(--soft); margin-bottom: 4px; }
textarea { width: 100%; resize: vertical; font: 13px/1.55 inherit; font-family: inherit; color: var(--text); background: var(--bg);
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
textarea:focus { outline: 2px solid color-mix(in srgb, var(--accent) 50%, transparent); border-color: var(--accent); }
.today { max-width: 1180px; margin: 0 auto; padding: 22px 24px 48px; }
.block { margin-bottom: 30px; }
.bhead { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.bhead h2 { font-size: 16px; }
.bhead .count { font-weight: 700; color: var(--stage); }
.bhead .hint { margin-left: auto; color: var(--muted); font-size: 13px; }
.empty { color: var(--muted); background: var(--panel); border: 1px dashed var(--line); border-radius: 12px; padding: 16px; margin: 0; }
.wide { display: grid; grid-template-columns: minmax(260px, 340px) 1fr; gap: 22px; background: var(--card);
  border: 1px solid var(--line); border-radius: 14px; padding: 18px; margin-bottom: 14px; }
.wide h3 { font-size: 17px; line-height: 1.3; margin-top: 10px; }
.wide .row { display: flex; align-items: center; gap: 10px; }
.wide .row .id { margin-left: auto; color: var(--muted); font-size: 12px; }
.steps { margin: 14px 0 0; padding: 0; list-style: none; counter-reset: s; font-size: 13px; color: var(--soft); }
.steps li { counter-increment: s; margin: 4px 0; }
.steps li::before { content: counter(s); display: inline-grid; place-items: center; width: 18px; height: 18px; margin-right: 8px;
  border-radius: 50%; background: var(--chip); color: var(--muted); font-size: 11px; font-weight: 700; }
.go { margin: 14px 0 0; }
.needs { display: flex; gap: 14px; align-items: flex-start; background: var(--card); border: 1px solid var(--line);
  border-left: 3px solid var(--red); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
.needs .grow { flex: 1; }
.needs h3 { font-size: 15px; }
.pipeline { display: grid; grid-template-columns: repeat(6, minmax(150px, 1fr)); gap: 10px; overflow-x: auto; }
.lane { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 10px; min-height: 120px; }
.lane h4 { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: var(--soft); display: flex; gap: 6px; align-items: center; }
.lane h4 i { width: 7px; height: 7px; border-radius: 50%; background: var(--stage); }
.lane h4 b { margin-left: auto; color: var(--muted); }
.mini { position: relative; color: var(--text); background: var(--card); border: 1px solid var(--line);
  border-radius: 8px; padding: 8px; margin-bottom: 6px; font-size: 12px; }
.mini:hover { border-color: var(--muted); }
.mini a { display: block; color: inherit; text-decoration: none; }
.x { position: absolute; top: 6px; right: 6px; padding: 0 6px; border: 0; border-radius: 6px; background: none;
  color: var(--muted); font: inherit; font-size: 16px; line-height: 22px; cursor: pointer; }
.x:hover { color: var(--red); background: var(--chip); }
.mini .t { display: block; font-weight: 600; font-size: 13px; line-height: 1.3; margin: 4px 0 2px; }
.mini .chip { margin-top: 4px; }
.lane .none { color: var(--muted); font-size: 12px; margin: 0; }
@media (max-width: 760px) { .wide { grid-template-columns: 1fr; } .needs { flex-wrap: wrap; } }
</style>
</head>
<body>
$body
<script>
document.addEventListener("click", function (event) {
  var move = event.target.closest("[data-move]");
  if (move) {
    move.disabled = true;
    fetch("/move", {method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({id: Number(move.dataset.move), status: move.dataset.status})})
      .then(function (response) { if (!response.ok) throw response; location.reload(); })
      .catch(function () { move.disabled = false; move.textContent = "Run: py -X utf8 board.py serve"; });
    return;
  }
  var button = event.target.closest("[data-copy]");
  if (!button) return;
  var box = document.getElementById(button.dataset.copy);
  box.select();
  function done() {
    button.textContent = "Copied";
    button.classList.add("done");
    setTimeout(function () { button.textContent = "Copy"; button.classList.remove("done"); }, 1500);
  }
  function fallback() { document.execCommand("copy"); done(); }
  if (navigator.clipboard) navigator.clipboard.writeText(box.value).then(done, fallback); else fallback();
});
</script>
</body>
</html>
"""


PORT = 8765


class Handler(BaseHTTPRequestHandler):
    """Serves board.html and takes the status changes its buttons send."""

    def do_GET(self):
        if self.path != "/":
            return self.send_error(404)
        self.reply(200, BOARD.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        # JSON from our own host name only: another site cannot send JSON here without a CORS preflight,
        # which this server never answers, and the Host check stops DNS rebinding.
        port = self.server.server_address[1]
        if (self.path != "/move" or self.headers.get("Content-Type") != "application/json"
                or self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}):
            return self.send_error(403)
        try:
            change = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            code = main(["move", f"{int(change['id'])}={change['status']}"])
        except (ValueError, KeyError, TypeError, SystemExit):  # bad body, or no such job
            code = 1
        self.reply(200 if code == 0 else 400, b"", "text/plain")

    def reply(self, code, body, kind):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv):
    if argv == ["serve"]:
        main([])
        print(f"Board at http://127.0.0.1:{PORT}/ (Ctrl+C to stop)")
        try:
            HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()  # one request at a time, so moves never race
        except KeyboardInterrupt:
            pass
        return 0
    data = json.loads(JOBS.read_text(encoding="utf-8")) if JOBS.exists() else {"last_run": None, "jobs": []}
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    notes = []
    if argv[:1] == ["apply"] and len(argv) == 2:
        inbox = json.loads(INBOX.read_text(encoding="utf-8")) if INBOX.exists() else []
        notes = apply_changes(data, json.loads(Path(argv[1]).read_text(encoding="utf-8")), inbox, stamp)
    elif argv[:1] == ["move"] and len(argv) > 1:
        notes = move(data, argv[1:], stamp)
    elif argv:
        raise SystemExit(__doc__)
    errors = check(data, FACTS.read_text(encoding="utf-8"))
    if errors:
        print("Not saved. Fix these first:", *errors, sep="\n  ")
        return 1
    JOBS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    BOARD.write_text(render(data, dt.date.fromisoformat(stamp[:10])), encoding="utf-8", newline="\n")
    counts = ", ".join(f"{label} {sum(job['status'] == key for job in data['jobs'])}" for key, label in COLUMNS)
    print(*notes, f"board.html: {counts}", sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
