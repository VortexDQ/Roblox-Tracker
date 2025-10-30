# 🎯 Roblox Tracker

A simple, lightweight Python tool that tracks **public Roblox user data** (profile, display name, presence, etc.) and posts updates to a **Discord webhook** as embeds — perfect for learning, personal analytics, or community alerts.

> ⚠️ **This tool only uses Roblox’s public APIs.**  
> Do **not** use it to access private data, accounts you don’t own, or anything that violates Roblox or Discord Terms of Service.

---

## 🧩 Features
- Tracks **public Roblox profiles** for selected usernames.
- Checks every few seconds (configurable).
- Sends **Discord embed updates** when something changes.
- Uses a simple `.env` file for setup (no hardcoded secrets).
- Minimal dependencies and clean console output.

---

## 🛠️ Setup Guide

### 1️⃣ Requirements
- Python **3.10+**
- A **Discord Webhook URL** (create one in your server’s channel settings)

### 2️⃣ Install dependencies
```bash
pip install -r requirements.txt
