import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load settings from .env
load_dotenv()
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
USERNAMES = [u.strip() for u in os.getenv("ROBLOX_USERNAMES", "").split(",") if u.strip()]
INTERVAL = float(os.getenv("POLL_INTERVAL_SECONDS", "10"))

if not WEBHOOK or not USERNAMES:
    print("❌ Please fill in .env first (webhook + usernames).")
    exit(1)

print(f"✅ Tracking {USERNAMES} every {INTERVAL}s...")

# Roblox API endpoints
USERNAME_URL = "https://users.roblox.com/v1/usernames/users"
USER_INFO_URL = "https://users.roblox.com/v1/users/{id}"
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"

# Store last known data to detect changes
last_info = {}

def resolve_usernames(names):
    """Convert usernames to user IDs."""
    res = requests.post(USERNAME_URL, json={"usernames": names}).json()
    mapping = {}
    for entry in res.get("data", []):
        mapping[entry["requestedUsername"]] = entry["id"]
    return mapping

def fetch_profile(uid):
    """Get basic user info."""
    r = requests.get(USER_INFO_URL.format(id=uid))
    if r.status_code != 200:
        return None
    data = r.json()
    return {
        "name": data.get("name"),
        "display": data.get("displayName"),
        "created": data.get("created"),
        "desc": data.get("description", "")
    }

def fetch_presence(uids):
    """Check if users are online / what game they're in."""
    r = requests.post(PRESENCE_URL, json={"userIds": uids})
    if r.status_code != 200:
        return {}
    out = {}
    for d in r.json().get("data", []):
        out[d["userId"]] = {
            "status": d.get("userPresenceType"),
            "place": d.get("lastLocation")
        }
    return out

def send_to_discord(username, changes):
    """Send update embed to Discord."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    embed = {
        "title": f"Update for {username}",
        "color": 0x00ADEF,
        "fields": [{"name": k, "value": f"`{old}` → `{new}`"} for k, (old, new) in changes.items()],
        "footer": {"text": f"Checked at {now}"}
    }
    requests.post(WEBHOOK, json={"embeds": [embed]})

def diff(old, new):
    """Find changed keys."""
    return {k: (old.get(k), new.get(k)) for k in new if old.get(k) != new.get(k)}

def main():
    ids = resolve_usernames(USERNAMES)
    print("Resolved IDs:", ids)

    while True:
        for user, uid in ids.items():
            profile = fetch_profile(uid)
            presence = fetch_presence([uid]).get(uid, {})
            combined = {**profile, **presence}

            if user in last_info:
                changes = diff(last_info[user], combined)
                if changes:
                    print(f"🔁 {user} changed:", changes)
                    send_to_discord(user, changes)
            else:
                print(f"👀 Tracking {user} started.")
                send_to_discord(user, {"status": ("none", "started")})

            last_info[user] = combined

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
