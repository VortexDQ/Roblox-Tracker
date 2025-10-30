# Roblox → Discord Public Tracker

Monitors **public** Roblox user profiles, avatar metadata and presence and posts changes as Discord embeds to a webhook you control.

**Important:** This tool fetches only public Roblox data. Do not use it to collect private or unauthorized data. Confirm compliance with Roblox/Discord ToS and local law.

---

## What’s included
- `roblox_to_discord_tracker.py` — main tracker script.
- `.env.example` — example environment file (copy to `.env`).
- `requirements.txt` — Python dependencies.
- `Dockerfile` & `docker-compose.yml` — optional containerized deployment.
- `roblox_tracker.service` — example systemd service unit.
- `.gitignore` — ignores secrets and common files.

---

## Quick start (local, recommended)
1. Install Python 3.10+ and `pip`.
2. Clone this repo and `cd` into it.
3. Create a Python virtualenv (recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
