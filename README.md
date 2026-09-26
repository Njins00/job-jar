# job-jar 🫙

A Telegram bot + web dashboard to track job applications on your own server.

## What it does

- Forward a job link to the bot
- Choose: Apply / Skip / Already Applied
- Get reminded every 12 hours if a job is still pending
- Upload resume and cover letter when you apply
- View everything on a local web dashboard

## Stack

- Python + python-telegram-bot
- Flask dashboard
- APScheduler for reminders
- JSON file storage (your data stays on your server)

## Setup

```bash
cp .env.example .env
# fill in your values in .env

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python bot.py       # run the bot
python dashboard.py # run the dashboard
```

## Self-hosted

Designed to run on a Raspberry Pi or any Linux server.
Data never leaves your machine.

## Bot commands

- Forward any job URL → bot saves it
- `/list` → show all pending jobs
- `/applied` → show applied jobs
- `/stats` → application stats

## Dashboard

Access at `http://YOUR_PI_IP:5000` on your local network.
