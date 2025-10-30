/**
 * tracker.js
 *
 * Advanced, responsible Roblox -> Discord public tracker (Node.js).
 *
 * - Polls public Roblox endpoints for usernames you configure.
 * - Persists last-known snapshots to local STATE_FILE so restarts do not re-notify.
 * - Sends Discord embeds only when there are meaningful changes.
 * - Implements retries/backoff and handles Discord 429 responses gracefully.
 *
 * Usage:
 *   1) npm install axios dotenv
 *   2) Configure .env (see example)
 *   3) node tracker.js
 *
 * NOTE: Use only on accounts you own or have permission to monitor.
 */

const fs = require('fs');
const path = require('path');
const axios = require('axios');
require('dotenv').config();

// ----------------- Configuration -----------------
const CONFIG = {
  DISCORD_WEBHOOK_URL: process.env.DISCORD_WEBHOOK_URL || '',
  ROBLOX_USERNAMES: (process.env.ROBLOX_USERNAMES || '').split(',').map(s => s.trim()).filter(Boolean),
  POLL_INTERVAL_SECONDS: Math.max(1, Number(process.env.POLL_INTERVAL_SECONDS || 10)),
  NOTIFY_COOLDOWN_SECONDS: Math.max(1, Number(process.env.NOTIFY_COOLDOWN_SECONDS || 30)),
  STATE_FILE: process.env.STATE_FILE || 'state.json',
  HTTP_TIMEOUT_SECONDS: Math.max(1, Number(process.env.HTTP_TIMEOUT_SECONDS || 10)),
  MAX_RETRIES: Math.max(0, Number(process.env.MAX_RETRIES || 3)),
  RETRY_BASE_MS: Math.max(100, Number(process.env.RETRY_BASE_MS || 500))
};

// Basic validation
if (!CONFIG.DISCORD_WEBHOOK_URL || !/^https:\/\/(canary\.)?discord(app)?\.com\/api\/webhooks\/.+/.test(CONFIG.DISCORD_WEBHOOK_URL)) {
  console.error("ERROR: Invalid or missing DISCORD_WEBHOOK_URL in .env");
  process.exit(1);
}
if (CONFIG.ROBLOX_USERNAMES.length === 0) {
  console.error("ERROR: No ROBLOX_USERNAMES specified in .env");
  process.exit(1);
}

// ----------------- Endpoints -----------------
const ENDPOINTS = {
  USERNAMES: 'https://users.roblox.com/v1/usernames/users',
  USER_BY_ID: id => `https://users.roblox.com/v1/users/${id}`,
  AVATAR: id => `https://avatar.roblox.com/v1/users/${id}/avatar`,
  PRESENCE: 'https://presence.roblox.com/v1/presence/users'
};

// ----------------- HTTP helpers with retry/backoff -----------------
const axiosInstance = axios.create({
  timeout: CONFIG.HTTP_TIMEOUT_SECONDS * 1000,
  headers: { 'User-Agent': 'RobloxDiscordTracker/1.0 (educational; local)' }
});

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function withRetries(fn, name = 'request') {
  let attempt = 0;
  while (true) {
    try {
      return await fn();
    } catch (err) {
      attempt++;
      const wait = CONFIG.RETRY_BASE_MS * Math.pow(2, attempt - 1);
      const isLast = attempt > CONFIG.MAX_RETRIES;
      // If it's a 429 from Discord, honor Retry-After header if present
      if (err && err.response && err.response.status === 429) {
        const ra = err.response.headers && err.response.headers['retry-after'];
        const raMs = ra ? Math.ceil(Number(ra) * 1000) : wait;
        console.warn(`[${name}] 429 Rate limited. Retry-After: ${raMs}ms`);
        if (isLast) throw err;
        await sleep(raMs);
        continue;
      }
      if (isLast) {
        console.error(`[${name}] failed after ${attempt} attempts: ${err.message || err}`);
        throw err;
      } else {
        console.warn(`[${name}] attempt ${attempt} failed: ${err.message || err}. Backing off ${wait}ms`);
        await sleep(wait);
      }
    }
  }
}

// ----------------- State persistence -----------------
function loadState(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf8');
      return JSON.parse(raw);
    }
  } catch (e) {
    console.warn("Failed to load state file:", e.message || e);
  }
  return { users: {}, lastNotifiedAt: {} };
}

function saveState(filePath, state) {
  try {
    fs.writeFileSync(filePath, JSON.stringify(state, null, 2), { encoding: 'utf8' });
  } catch (e) {
    console.error("Failed to save state file:", e.message || e);
  }
}

// ----------------- Roblox data functions -----------------
async function resolveUsernamesToIds(usernames) {
  const payload = { usernames: usernames, excludeBannedUsers: false };
  const res = await withRetries(() => axiosInstance.post(ENDPOINTS.USERNAMES, payload), 'resolveUsernames');
  const data = res.data || {};
  const mapping = {};
  (data.data || []).forEach(entry => {
    const req = entry.requestedUsername || entry.name;
    if (req) mapping[req] = entry.id;
  });
  // best-effort: try case-insensitive matches
  for (const u of usernames) {
    if (!mapping[u] && Object.keys(mapping).length) {
      const key = Object.keys(mapping).find(k => k.toLowerCase() === u.toLowerCase());
      if (key) mapping[u] = mapping[key];
    }
  }
  return mapping;
}

async function fetchUserProfile(userId) {
  const res = await withRetries(() => axiosInstance.get(ENDPOINTS.USER_BY_ID(userId)), 'fetchProfile');
  return res.data;
}

async function fetchAvatar(userId) {
  const res = await withRetries(() => axiosInstance.get(ENDPOINTS.AVATAR(userId)), 'fetchAvatar');
  return res.data;
}

async function fetchPresenceBatch(userIds) {
  if (!userIds || userIds.length === 0) return {};
  const res = await withRetries(() => axiosInstance.post(ENDPOINTS.PRESENCE, { userIds }), 'fetchPresence');
  // response may be list or { data: [] }
  const payload = res.data;
  const list = Array.isArray(payload) ? payload : (payload.data || []);
  const map = {};
  for (const p of list) {
    map[p.userId] = p;
  }
  // ensure keys for all requested
  for (const uid of userIds) if (!map[uid]) map[uid] = {};
  return map;
}

// ----------------- Utilities / comparison -----------------
function compactProfile(profile) {
  if (!profile) return {};
  return {
    id: profile.id,
    name: profile.name,
    displayName: profile.displayName || '',
    created: profile.created || '',
    description: profile.description || ''
  };
}

function compactAvatar(avatar) {
  if (!avatar) return {};
  return {
    playerAvatarType: avatar.playerAvatarType,
    assetsCount: (avatar.assets || []).length
  };
}

function compactPresence(pres) {
  if (!pres) return {};
  return {
    userPresenceType: pres.userPresenceType,
    lastLocation: pres.lastLocation || '',
    placeId: pres.placeId || null,
    gameId: pres.gameId || null,
    lastOnline: pres.lastOnline || null
  };
}

function diffObjects(oldObj, newObj) {
  const diffs = {};
  const keys = new Set([...Object.keys(oldObj || {}), ...Object.keys(newObj || {})]);
  for (const k of keys) {
    const ov = oldObj ? oldObj[k] : undefined;
    const nv = newObj ? newObj[k] : undefined;
    // simple deep-equality for primitives; arrays/objects stringify for comparsion
    const oe = (ov !== null && typeof ov === 'object') ? JSON.stringify(ov) : ov;
    const ne = (nv !== null && typeof nv === 'object') ? JSON.stringify(nv) : nv;
    if (oe !== ne) diffs[k] = { before: ov, after: nv };
  }
  return diffs;
}

// Map Roblox presence codes to friendly strings
function presenceTypeName(code) {
  // common mapping: 0 or 1 => offline, 2 => online, 3 => inGame. Different endpoints vary.
  if (code === 2) return 'Online';
  if (code === 3) return 'In Game';
  if (code === 1 || code === 0) return 'Offline';
  return code ? `${code}` : 'Unknown';
}

// ----------------- Discord embed builder & sender -----------------
function buildEmbed(username, uid, profileCompact, avatarCompact, presenceCompact, diffs) {
  const presenceName = presenceTypeName(presenceCompact.userPresenceType);
  // choose color: green for online, red for in-game, grey for offline
  const color = presenceName === 'In Game' ? 0xE74C3C : (presenceName === 'Online' ? 0x2ECC71 : 0x95A5A6);
  const icon = presenceName === 'In Game' ? '🎮' : (presenceName === 'Online' ? '🟢' : '⚪');

  const avatarUrl = `https://www.roblox.com/headshot-thumbnail/image?userId=${uid}&width=150&height=150&format=png`;

  const title = `${icon} ${presenceName} — ${profileCompact.name || username}`;
  const fields = [];

  // Add diff sections if present
  if (diffs.profile && Object.keys(diffs.profile).length) {
    const lines = [];
    for (const [k, v] of Object.entries(diffs.profile)) {
      lines.push(`**${k}**: \`${String(v.before)}\` → \`${String(v.after)}\``);
    }
    fields.push({ name: 'Profile changes', value: lines.join('\n').slice(0, 1024), inline: false });
  }
  if (diffs.avatar && Object.keys(diffs.avatar).length) {
    const lines = [];
    for (const [k, v] of Object.entries(diffs.avatar)) {
      lines.push(`**${k}**: \`${String(v.before)}\` → \`${String(v.after)}\``);
    }
    fields.push({ name: 'Avatar changes', value: lines.join('\n').slice(0, 1024), inline: false });
  }
  if (diffs.presence && Object.keys(diffs.presence).length) {
    const lines = [];
    for (const [k, v] of Object.entries(diffs.presence)) {
      lines.push(`**${k}**: \`${String(v.before)}\` → \`${String(v.after)}\``);
    }
    fields.push({ name: 'Presence changes', value: lines.join('\n').slice(0, 1024), inline: false });
  }

  // Summary snapshot
  const snapshot = [
    `ID: ${uid}`,
    `Name: ${profileCompact.name || ''}`,
    `DisplayName: ${profileCompact.displayName || ''}`,
    `Status: ${presenceName}`,
    presenceCompact.lastLocation ? `Location: ${presenceCompact.lastLocation}` : null
  ].filter(Boolean).join('\n');

  fields.push({ name: 'Snapshot', value: snapshot.slice(0, 1024), inline: false });

  const embed = {
    title,
    url: `https://www.roblox.com/users/${uid}/profile`,
    color,
    thumbnail: { url: avatarUrl },
    fields,
    timestamp: new Date().toISOString(),
    footer: { text: 'Public-only monitoring' }
  };

  return embed;
}

async function sendDiscordEmbed(embed) {
  const payload = { embeds: [embed] };
  return withRetries(() => axiosInstance.post(CONFIG.DISCORD_WEBHOOK_URL, payload, {
    headers: { 'Content-Type': 'application/json' }
  }), 'sendDiscord');
}

// ----------------- Main logic -----------------
(async function main() {
  console.log('Starting Roblox -> Discord tracker (responsible mode)');
  console.log(`Usernames: ${CONFIG.ROBLOX_USERNAMES.join(', ')}`);
  console.log(`Poll interval: ${CONFIG.POLL_INTERVAL_SECONDS}s`);
  console.log(`Notify cooldown (per user): ${CONFIG.NOTIFY_COOLDOWN_SECONDS}s`);
  const statePath = path.resolve(CONFIG.STATE_FILE);
  const persisted = loadState(statePath);

  // Map usernames -> userIds
  let nameToId = await resolveUsernamesToIds(CONFIG.ROBLOX_USERNAMES);
  // Filter out missing
  CONFIG.ROBLOX_USERNAMES = CONFIG.ROBLOX_USERNAMES.filter(u => {
    if (!nameToId[u]) {
      console.warn(`Warning: Could not resolve username: ${u} (skipping)`);
      return false;
    }
    return true;
  });

  // Initialize last known state for each username
  for (const username of CONFIG.ROBLOX_USERNAMES) {
    const uid = nameToId[username];
    if (!persisted.users[username]) persisted.users[username] = { profile: {}, avatar: {}, presence: {} };
    // Ensure lastNotifiedAt has an entry
    if (!persisted.lastNotifiedAt[username]) persisted.lastNotifiedAt[username] = 0;
    // attach id for convenience
    persisted.users[username].uid = uid;
  }

  // Save initial state file
  saveState(statePath, persisted);

  // Poll loop
  while (true) {
    const start = Date.now();
    try {
      // Refresh presence in batch
      const uids = CONFIG.ROBLOX_USERNAMES.map(u => persisted.users[u].uid);
      const presenceMap = await fetchPresenceBatch(uids);

      // For each user, fetch profile + avatar (can be throttled if many users)
      for (const username of CONFIG.ROBLOX_USERNAMES) {
        const uid = persisted.users[username].uid;
        // Fetch profile and avatar (sequentially to avoid bursts)
        let profile = null;
        let avatar = null;
        try {
          profile = await fetchUserProfile(uid);
        } catch (e) {
          console.warn(`Failed to fetch profile ${username} (${uid}): ${e.message || e}`);
        }
        try {
          avatar = await fetchAvatar(uid);
        } catch (e) {
          console.warn(`Failed to fetch avatar ${username} (${uid}): ${e.message || e}`);
        }
        const presence = presenceMap[uid] || {};

        const compactP = compactProfile(profile);
        const compactA = compactAvatar(avatar);
        const compactPr = compactPresence(presence);

        const prev = persisted.users[username] || { profile: {}, avatar: {}, presence: {} };
        const prevProfile = prev.profile || {};
        const prevAvatar = prev.avatar || {};
        const prevPresence = prev.presence || {};

        const diffs = {
          profile: diffObjects(prevProfile, compactP),
          avatar: diffObjects(prevAvatar, compactA),
          presence: diffObjects(prevPresence, compactPr)
        };

        // Decide whether to notify:
        const hasChanges = (Object.keys(diffs.profile).length + Object.keys(diffs.avatar).length + Object.keys(diffs.presence).length) > 0;

        // Cooldown check: do not notify too frequently per user
        const now = Date.now();
        const lastNotified = persisted.lastNotifiedAt[username] || 0;
        const cooldownMs = CONFIG.NOTIFY_COOLDOWN_SECONDS * 1000;
        const allowed = (now - lastNotified) >= cooldownMs;

        if (hasChanges && allowed) {
          // Build and send embed
          const embed = buildEmbed(username, uid, compactP, compactA, compactPr, diffs);
          try {
            await sendDiscordEmbed(embed);
            console.log(`[${new Date().toISOString()}] Notified changes for ${username}`);
            persisted.lastNotifiedAt[username] = Date.now();
          } catch (e) {
            console.error(`Failed to send Discord embed for ${username}: ${e.message || e}`);
          }
        } else if (hasChanges && !allowed) {
          // If there are changes but cooldown is active, log but do not spam Discord
          console.log(`[${new Date().toISOString()}] Changes detected for ${username} but cooldown active. Will not notify.`);
        } else {
          // nothing changed
          // console.debug(`[${new Date().toISOString()}] No changes for ${username}`);
        }

        // Update persisted state
        persisted.users[username] = {
          uid,
          profile: compactP,
          avatar: compactA,
          presence: compactPr
        };

        // Minor pause to avoid burstiness if many users (safe default)
        await sleep(150);
      }

      // Save state after the full pass
      saveState(statePath, persisted);

    } catch (err) {
      console.error("Unhandled loop error:", err.message || err);
    }

    // Wait until next interval, accounting for work time
    const elapsed = Date.now() - start;
    const wait = Math.max(0, CONFIG.POLL_INTERVAL_SECONDS * 1000 - elapsed);
    await sleep(wait);
  }

})().catch(err => {
  console.error("Fatal error:", err);
  process.exit(1);
});
