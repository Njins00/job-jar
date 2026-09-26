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

# status display config
STATUS_META = {
    "pending":    {"emoji": "🟡", "label": "Pending"},
    "applied":    {"emoji": "✅", "label": "Applied"},
    "skipped":    {"emoji": "❌", "label": "Skipped"},
    "interview":  {"emoji": "📞", "label": "Interview"},
    "rejected":   {"emoji": "🚫", "label": "Rejected"},
    "offered":    {"emoji": "🎉", "label": "Offered"},
}

ALL_STATUSES = list(STATUS_META.keys())

# inline HTML template — keeps it one file, no templates folder needed
PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job-jar 🫙</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f0f0f; color: #e0e0e0; padding: 24px; }
  h1   { font-size: 1.6rem; margin-bottom: 4px; }
  .sub { color: #888; font-size: 0.85rem; margin-bottom: 24px; }

  /* stats bar */
  .stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }
  .stat  { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px;
            padding: 12px 18px; min-width: 100px; }
  .stat .num  { font-size: 1.5rem; font-weight: 600; }
  .stat .lbl  { font-size: 0.75rem; color: #888; margin-top: 2px; }

  /* section */
  .section { margin-bottom: 32px; }
  .section h2 { font-size: 1rem; color: #aaa; margin-bottom: 12px;
                text-transform: uppercase; letter-spacing: .05em; }

  /* job card */
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
          padding: 16px; margin-bottom: 10px; }
  .card-title { font-size: 1rem; font-weight: 500; margin-bottom: 4px; }
  .card-url   { font-size: 0.8rem; color: #4a9eff; word-break: break-all;
                margin-bottom: 8px; }
  .card-url a { color: #4a9eff; text-decoration: none; }
  .card-url a:hover { text-decoration: underline; }
  .card-meta  { font-size: 0.78rem; color: #666; margin-bottom: 10px; }
  .card-files { font-size: 0.78rem; margin-bottom: 10px; }
  .card-files a { color: #4a9eff; text-decoration: none; margin-right: 12px; }
  .card-files a:hover { text-decoration: underline; }

  /* status form */
  .status-form { display: flex; gap: 6px; flex-wrap: wrap; }
  .status-form select {
    background: #111; color: #e0e0e0; border: 1px solid #333;
    border-radius: 6px; padding: 4px 8px; font-size: 0.8rem; }
  .status-form button {
    background: #2a2a2a; color: #e0e0e0; border: 1px solid #333;
    border-radius: 6px; padding: 4px 12px; font-size: 0.8rem;
    cursor: pointer; }
  .status-form button:hover { background: #333; }

  .empty { color: #555; font-size: 0.9rem; padding: 12px 0; }
</style>
</head>
<body>

<h1>job-jar 🫙</h1>
<p class="sub">Last updated: {{ now }}</p>

<!-- stats -->
<div class="stats">
  {% for key, meta in status_meta.items() %}
  <div class="stat">
    <div class="num">{{ counts.get(key, 0) }}</div>
    <div class="lbl">{{ meta.emoji }} {{ meta.label }}</div>
  </div>
  {% endfor %}
  <div class="stat">
    <div class="num">{{ total }}</div>
    <div class="lbl">📋 Total</div>
  </div>
</div>

<!-- jobs by status -->
{% for status, meta in status_meta.items() %}
<div class="section">
  <h2>{{ meta.emoji }} {{ meta.label }} ({{ counts.get(status, 0) }})</h2>
  {% set group = jobs_by_status.get(status, []) %}
  {% if group %}
    {% for job in group %}
    <div class="card">
      <div class="card-title">{{ job.title }}</div>
      <div class="card-url"><a href="{{ job.url }}" target="_blank">{{ job.url }}</a></div>
      <div class="card-meta">
        Added: {{ job.added[:10] }}
        {% if job.applied_date %} &nbsp;·&nbsp; Applied: {{ job.applied_date[:10] }}{% endif %}
      </div>

      {% if job.resume or job.cover_letter %}
      <div class="card-files">
        {% if job.resume %}
          <a href="/download/{{ job.id }}/resume">📄 Resume</a>
        {% endif %}
        {% if job.cover_letter %}
          <a href="/download/{{ job.id }}/cover">📝 Cover Letter</a>
        {% endif %}
      </div>
      {% endif %}

      <form class="status-form" method="POST" action="/update/{{ job.id }}">
        <select name="status">
          {% for s, m in status_meta.items() %}
          <option value="{{ s }}" {% if s == job.status %}selected{% endif %}>
            {{ m.emoji }} {{ m.label }}
          </option>
          {% endfor %}
        </select>
        <button type="submit">Update</button>
      </form>
    </div>
    {% endfor %}
  {% else %}
    <p class="empty">None</p>
  {% endif %}
</div>
{% endfor %}

</body>
</html>
"""


def load_jobs() -> dict:
    if not Path(DATA_FILE).exists():
        return {}
    with open(DATA_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


@app.route("/")
def index():
    jobs = load_jobs()

    # group by status
    jobs_by_status = {s: [] for s in ALL_STATUSES}
    counts = {s: 0 for s in ALL_STATUSES}

    for job in jobs.values():
        s = job.get("status", "pending")
        if s in jobs_by_status:
            jobs_by_status[s].append(job)
            counts[s] += 1

    # sort each group newest first
    for s in jobs_by_status:
        jobs_by_status[s].sort(key=lambda j: j.get("added", ""), reverse=True)

    return render_template_string(
        PAGE,
        jobs_by_status=jobs_by_status,
        counts=counts,
        total=len(jobs),
        status_meta=STATUS_META,
        now=datetime.now().strftime("%d %b %Y %H:%M"),
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
    # set applied_date when moving to applied
    if new_status == "applied" and not jobs[job_id].get("applied_date"):
        jobs[job_id]["applied_date"] = datetime.now().isoformat()
    save_jobs(jobs)
    return redirect(url_for("index"))


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
