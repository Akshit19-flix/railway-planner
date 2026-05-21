# How to get a permanent shareable link

## Option A — Render.com (recommended, free, permanent URL)

Render hosts Docker apps for free. Your app will be at a URL like:
**https://railways-planner.onrender.com**

### Step 1 — Put the code on GitHub (one-time, 5 minutes)

1. Go to https://github.com and sign up / log in
2. Click **New repository** → name it `railways-planner` → click **Create repository**
3. Open Command Prompt in the project folder and run:

```
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/railways-planner.git
git push -u origin main
```

(Replace YOUR_USERNAME with your GitHub username)

### Step 2 — Deploy on Render (one-time, 3 minutes)

1. Go to https://render.com and sign up with your GitHub account
2. Click **New +** → **Web Service**
3. Connect your GitHub account → select `railways-planner` repository
4. Render auto-detects the Dockerfile — just click **Create Web Service**
5. Wait ~5 minutes for the first build

Your permanent URL will be shown at the top of the Render dashboard.
**Share this URL with anyone — it works on any device, any time.**

### Updating the app later

After any code change, just run:
```
git add .
git commit -m "Update"
git push
```
Render redeploys automatically within 2–3 minutes.

### Free tier limits

- Spins down after 15 min of inactivity → first visit after idle takes ~30s to wake up
- 512 MB RAM, 0.1 CPU — fine for a few concurrent users
- Upgrade to $7/month Starter plan if you need it always-on

---

## Option B — Share on your office network (no account needed)

While your PC is running the app:

1. Open Command Prompt and run `ipconfig` → note your **IPv4 Address** (e.g. `192.168.1.45`)
2. Stop the normal `start.bat` and run this instead:
   ```
   python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
   ```
3. Anyone on the same WiFi/VPN opens: `http://192.168.1.45:8501`

Works as long as your PC is on and the app is running.

---

## Option C — Copy to another PC

1. Copy the entire project folder (USB / shared drive / zip)
2. Recipient runs `setup.bat` once
3. Then `start.bat` any time — or `create_shortcut.bat` for a Desktop icon
