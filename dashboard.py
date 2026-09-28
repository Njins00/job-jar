import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template_string, send_file, redirect, url_for, request, abort

load_dotenv()

DATA_FILE  = os.getenv("DATA_FILE", "jobs.json")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
DASH_PORT  = int(os.getenv("DASHBOARD_PORT", 5000))

app = Flask(__name__)

STATUS_META = {
    "pending":   {"emoji": "🟡", "label": "Pending",   "color": "#f59e0b"},
    "applied":   {"emoji": "✅", "label": "Applied",   "color": "#10b981"},
    "skipped":   {"emoji": "❌", "label": "Skipped",   "color": "#6b7280"},
    "interview": {"emoji": "📞", "label": "Interview", "color": "#3b82f6"},
    "rejected":  {"emoji": "🚫", "label": "Rejected",  "color": "#ef4444"},
    "offered":   {"emoji": "🎉", "label": "Offered",   "color": "#8b5cf6"},
}

ALL_STATUSES = list(STATUS_META.keys())

# ------------------------------------------------------------------ templates

BASE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}job-jar{% endblock %} 🫙</title>
<style>
:root {
  --bg:      #0a0a0a;
  --surface: #111111;
  --card:    #1a1a1a;
  --border:  #2a2a2a;
  --text:    #e5e5e5;
  --muted:   #6b7280;
  --accent:  #3b82f6;
  --radius:  12px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text);
  min-height: 100vh; padding: 0;
}

/* nav */
nav {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 24px;
  display: flex; align-items: center; gap: 16px;
}
nav a.brand {
  font-size: 1.1rem; font-weight: 600;
  color: var(--text); text-decoration: none;
}
nav a.brand span { color: var(--muted); font-weight: 400; }
nav .spacer { flex: 1; }
nav a.nav-link {
  color: var(--muted); text-decoration: none;
  font-size: 0.85rem; padding: 6px 12px;
  border-radius: 8px; transition: background .15s;
}
nav a.nav-link:hover { background: var(--card); color: var(--text); }

/* main */
main { max-width: 900px; margin: 0 auto; padding: 28px 20px; }

/* stats */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px; margin-bottom: 28px;
}
.stat {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px;
  text-align: center;
}
.stat .num { font-size: 1.8rem; font-weight: 700; line-height: 1; }
.stat .lbl { font-size: 0.72rem; color: var(--muted); margin-top: 4px; }

/* section */
.section { margin-bottom: 32px; }
.section-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 12px;
  font-size: 0.78rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted);
}
.section-header .count {
  background: var(--border); color: var(--muted);
  border-radius: 20px; padding: 1px 8px;
  font-size: 0.72rem;
}

/* job card */
.job-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px;
  margin-bottom: 8px; display: flex;
  align-items: flex-start; gap: 14px;
  cursor: pointer; text-decoration: none; color: inherit;
  transition: border-color .15s;
}
.job-card:hover { border-color: #444; }
.job-card .dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-top: 6px; flex-shrink: 0;
}
.job-card .body { flex: 1; min-width: 0; }
.job-card .title {
  font-size: 0.95rem; font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.job-card .meta {
  font-size: 0.75rem; color: var(--muted); margin-top: 4px;
}
.job-card .arrow { color: var(--muted); font-size: 0.85rem; align-self: center; }

/* empty */
.empty { color: var(--muted); font-size: 0.85rem; padding: 8px 0; }

/* job detail */
.detail-header { margin-bottom: 24px; }
.detail-header h1 { font-size: 1.3rem; font-weight: 600; margin-bottom: 6px; }
.detail-header .url a {
  color: var(--accent); font-size: 0.85rem;
  text-decoration: none; word-break: break-all;
}
.detail-header .url a:hover { text-decoration: underline; }

.detail-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 10px; margin-bottom: 24px;
}
.detail-box {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px;
}
.detail-box .lbl { font-size: 0.72rem; color: var(--muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: .05em; }
.detail-box .val { font-size: 0.95rem; }

/* status form */
.status-row {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px;
  margin-bottom: 12px;
  display: flex; align-items: center; gap: 12px;
}
.status-row label { font-size: 0.85rem; color: var(--muted); }
.status-row select {
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 6px 10px; font-size: 0.85rem; flex: 1;
}
.btn {
  background: var(--accent); color: #fff;
  border: none; border-radius: 8px;
  padding: 7px 16px; font-size: 0.85rem;
  cursor: pointer; text-decoration: none;
  display: inline-block;
}
.btn:hover { opacity: .9; }
.btn.secondary {
  background: var(--card); color: var(--text);
  border: 1px solid var(--border);
}
.btn.secondary:hover { background: var(--border); }

/* files */
.files { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }

/* back link */
.back { color: var(--muted); font-size: 0.85rem; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; margin-bottom: 20px; }
.back:hover { color: var(--text); }
</style>
</head>
<body>
<nav>
  <a class="brand" href="/">job-jar <span>🫙</span></a>
  <div class="spacer"></div>
  <a class="nav-link" href="/">Dashboard</a>
</nav>
<main>
{% block content %}{% endblock %}
</main>
</body>
</html>
"""

INDEX = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}

<!-- stats -->
<div class="stats">
  {% for key, meta in status_meta.items() %}
  <div class="stat">
    <div class="num" style="color:{{ meta.color }}">{{ counts.get(key, 0) }}</div>
    <div class="lbl">{{ meta.emoji }} {{ meta.label }}</div>
  </div>
  {% endfor %}
  <div class="stat">
    <div class="num">{{ total }}</div>
    <div class="lbl">📋 Total</div>
  </div>
</div>

<!-- job groups -->
{% for status, meta in status_meta.items() %}
{% set group = jobs_by_status.get(status, []) %}
<div class="section">
  <div class="section-header">
    {{ meta.emoji }} {{ meta.label }}
    <span class="count">{{ group|length }}</span>
  </div>
  {% if group %}
    {% for job in group %}
    <a class="job-card" href="/job/{{ job.id }}">
      <div class="dot" style="background:{{ meta.color }}"></div>
      <div class="body">
        <div class="title">{{ job.title }}</div>
        <div class="meta">
          Added {{ job.added[:10] }}
          {% if job.applied_date %} · Applied {{ job.applied_date[:10] }}{% endif %}
          {% if job.resume or job.cover_letter %} · 📎 Files attached{% endif %}
        </div>
      </div>
      <div class="arrow">›</div>
    </a>
    {% endfor %}
  {% else %}
    <p class="empty">Nothing here</p>
  {% endif %}
</div>
{% endfor %}

{% endblock %}
""")

DETAIL = BASE.replace("{% block content %}{% endblock %}", """
{% block content %}

<a class="back" href="/">← Back</a>

<div class="detail-header">
  <h1>{{ job.title }}</h1>
  <div class="url"><a href="{{ job.url }}" target="_blank">{{ job.url }}</a></div>
</div>

<div class="detail-grid">
  <div class="detail-box">
    <div class="lbl">Status</div>
    <div class="val">{{ status_meta[job.status].emoji }} {{ status_meta[job.status].label }}</div>
  </div>
  <div class="detail-box">
    <div class="lbl">Added</div>
    <div class="val">{{ job.added[:10] }}</div>
  </div>
  {% if job.applied_date %}
  <div class="detail-box">
    <div class="lbl">Applied</div>
    <div class="val">{{ job.applied_date[:10] }}</div>
  </div>
  {% endif %}
  <div class="detail-box">
    <div class="lbl">Reminders sent</div>
    <div class="val">{{ job.get('reminder_count', 0) }}</div>
  </div>
</div>

<!-- files -->
{% if job.resume or job.cover_letter %}
<div class="files">
  {% if job.resume %}
  <a class="btn secondary" href="/download/{{ job.id }}/resume">📄 Resume</a>
  {% endif %}
  {% if job.cover_letter %}
  <a class="btn secondary" href="/download/{{ job.id }}/cover">📝 Cover Letter</a>
  {% endif %}
</div>
{% endif %}

<!-- status update -->
<form class="status-row" method="POST" action="/update/{{ job.id }}">
  <label>Update status</label>
  <select name="status">
    {% for s, m in status_meta.items() %}
    <option value="{{ s }}" {% if s == job.status %}selected{% endif %}>
      {{ m.emoji }} {{ m.label }}
    </option>
    {% endfor %}
  </select>
  <button class="btn" type="submit">Save</button>
</form>

<a class="btn secondary" href="{{ job.url }}" target="_blank">🌐 Open Job Listing</a>

{% endblock %}
""")


# ------------------------------------------------------------------ helpers

def load_jobs() -> dict:
    if not Path(DATA_FILE).exists():
        return {}
    with open(DATA_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


# ------------------------------------------------------------------ routes

@app.route("/")
def index():
    jobs = load_jobs()
    jobs_by_status = {s: [] for s in ALL_STATUSES}
    counts = {s: 0 for s in ALL_STATUSES}

    for job in jobs.values():
        s = job.get("status", "pending")
        if s in jobs_by_status:
            jobs_by_status[s].append(job)
            counts[s] += 1

    for s in jobs_by_status:
        jobs_by_status[s].sort(key=lambda j: j.get("added", ""), reverse=True)

    return render_template_string(
        INDEX,
        jobs_by_status=jobs_by_status,
        counts=counts,
        total=len(jobs),
        status_meta=STATUS_META,
    )


@app.route("/job/<job_id>")
def job_detail(job_id):
    jobs = load_jobs()
    if job_id not in jobs:
        abort(404)
    job = jobs[job_id]
    return render_template_string(
        DETAIL,
        job=job,
        status_meta=STATUS_META,
    )


@app.route("/update/<job_id>", methods=["POST"])
def update_status(job_id):
    new_status = request.form.get("status")
    if new_status not in ALL_STATUSES:
        abort(400)
    jobs = load_jobs()
    if job_id not in jobs:
        abort(404)
    jobs[job_id]["status"] = new_status
    if new_status == "applied" and not jobs[job_id].get("applied_date"):
        jobs[job_id]["applied_date"] = datetime.now().isoformat()
    save_jobs(jobs)
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/download/<job_id>/<file_type>")
def download_file(job_id, file_type):
    if file_type not in ("resume", "cover"):
        abort(400)
    jobs = load_jobs()
    if job_id not in jobs:
        abort(404)
    job = jobs[job_id]
    path = job.get("resume") if file_type == "resume" else job.get("cover_letter")
    if not path or not Path(path).exists():
        abort(404)
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=DASH_PORT, debug=False)
