# Deploying API Sentinel for free

**Stack:** Render (free web service, Docker) + Supabase (free PostgreSQL). Cost: **$0/month**, no credit card.

| Piece | Free tier facts that matter |
|---|---|
| **Render web service** | 750 instance-hours/month (enough for 24/7). Spins down after **15 min without inbound traffic**. 512 MB RAM. |
| **Supabase Postgres** | 500 MB database, no compute-hour cap. Pauses only after **7 days of inactivity**. |

**Why this combo works for a monitor:**
- Render's own free Postgres is deleted after 30 days, so the database lives on Supabase instead.
- Sentinel monitors its own built-in demo API (`/demo/*`) through its public URL every 20–30 s. That inbound traffic stops Render from spinning it down.
- The constant writes mean Supabase never sees a week of inactivity, so it never pauses.

> ⚠️ Render's free tier is meant for hobby projects, and Render discourages artificially keeping free
> services awake. That's fine for a portfolio demo. For anything serious, use Option B below (an
> always-free VM) or a paid instance.

---

## 1. Push the code to GitHub

```bash
git init && git add . && git commit -m "API Sentinel v2"
git branch -M main
git remote add origin https://github.com/<you>/api-sentinel.git
git push -u origin main
```

## 2. Create the database on Supabase

1. Go to <https://supabase.com> and sign in with GitHub. Click **New project**.
2. Pick a name, **generate a strong database password and save it**, and choose the region closest to
   you (e.g. *South Asia (Mumbai)*).
3. When the project is ready, click **Connect** (top bar) and choose **Session pooler**. Use the session
   pooler because Render needs IPv4 and the direct connection is IPv6-only. Copy the URI. It looks like:

   ```
   postgresql://postgres.abcdefghijkl:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```

4. Replace `[YOUR-PASSWORD]` with your password and add `?sslmode=require` at the end.
   If the password contains special characters (`@ # / : ?`), URL-encode them (e.g. `@` → `%40`).

You don't need to create any tables. Sentinel runs its migrations automatically on startup.

## 3. Deploy on Render

1. Go to <https://render.com> and sign in with GitHub. Click **New → Blueprint**.
2. Select your `api-sentinel` repository. Render detects `render.yaml`.
3. When asked for `SENTINEL_DATABASE_URL`, paste the Supabase URL from step 2.
   `SENTINEL_ALERT_WEBHOOK_URL` is optional; leave it empty or paste a Slack/Discord webhook URL.
4. Click **Apply**. The first build (React + Python) takes about 5–8 minutes.
5. Open `https://api-sentinel-xxxx.onrender.com`. Six demo endpoints are created automatically and
   start reporting within a minute.

## 4. Log in as admin

Anyone can view the dashboard, but changes need the admin key:

1. Render dashboard → your service → **Environment** → copy the value of `SENTINEL_API_KEY`
   (Render generated it for you).
2. In Sentinel, go to **Settings → Admin key**, paste it, and click **Save & verify**.

Now you can add endpoints, pause them, start maintenance windows and use the **chaos controls**.

## 5. Turn on email alerts (Brevo, free)

Render's free tier **blocks outgoing SMTP** (ports 25/465/587), so Gmail SMTP won't work there.
Sentinel sends email through **Brevo's HTTPS API** instead (free: 300 emails/day, no card).

1. Sign up at <https://www.brevo.com> (free plan).
2. **Senders, domains & dedicated IPs → Senders → Add a sender**: enter the email you want alerts
   to come *from* (e.g. your Gmail) and click the verification link Brevo emails you.
3. **SMTP & API → API keys → Generate a new API key**. Copy it (starts with `xkeysib-`).
4. In Render → your service → **Environment**, set:
   - `SENTINEL_BREVO_API_KEY` = the key
   - `SENTINEL_EMAIL_FROM` = the verified sender address
   (`SENTINEL_EMAIL_PROVIDER=brevo` is already set by `render.yaml`.) Save; Render redeploys.
5. In the dashboard open an endpoint → **Settings → Alert contacts**, add your friend's email, click
   **Save contacts**, then **Send test email**.

Now when that API goes down, recovers, slows down abnormally or its TLS certificate nears expiry,
your friend gets an email like this:

![Alert email](docs/screenshots/email.png)

> Tip: emails from a free Gmail sender can land in spam at first. Ask recipients to mark the first one
> "Not spam". For best deliverability, verify your own domain in Brevo later.

**Running locally instead?** You can use Gmail SMTP: create an
[app password](https://myaccount.google.com/apppasswords) and set the `SENTINEL_SMTP_*` variables from
`.env.example` with `SENTINEL_EMAIL_PROVIDER=smtp`.

## 6. Backup keep-alive (recommended)

If Render ever restarts the service, the self-monitoring traffic resumes as soon as it boots. As a
safety net, add a free external ping:

1. <https://cron-job.org> → sign up → **Create cronjob**.
2. URL: `https://<your-app>.onrender.com/health/live`, schedule **every 10 minutes**.

## 7. Share it

| Link | Use it for |
|---|---|
| `https://<your-app>.onrender.com/` | Live dashboard (put it on your resume) |
| `https://<your-app>.onrender.com/status` | Public status page |
| `https://<your-app>.onrender.com/docs` | Interactive API docs |

**Demo script for interviews:** open the dashboard, go to Settings → **Take it down**, and switch back
to Overview. Within about 40 s, `demo-orders` turns red, a DOWN alert pops up live, and the status
page shows a partial outage. Click **Healthy** to watch it recover.

---

## Option B: Oracle Cloud "Always Free" VM (truly always-on)

Oracle's Always Free tier includes small VMs that never sleep. A card is needed for identity
verification, but you are not charged.

```bash
# on the VM (Ubuntu)
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone https://github.com/<you>/api-sentinel.git && cd api-sentinel
echo "SENTINEL_API_KEY=$(openssl rand -hex 24)" > .env
sudo docker compose up -d --build
```

Open port 8000 in the VM's security list (or put Caddy/Nginx in front for HTTPS), then visit
`http://<vm-ip>:8000`. To lock it down, also set `SENTINEL_BLOCK_PRIVATE_TARGETS=true` in `.env`.
That stops anyone from registering internal addresses. The built-in demo endpoints keep working.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy fails with `password authentication failed` | Wrong password in the URL, or special characters not URL-encoded. |
| `connection refused` / timeout to Supabase | You used the *direct* connection (IPv6). Use the **Session pooler** URI. |
| Dashboard shows "Reconnecting…" | Free instance is waking up (up to ~1 min). Refresh after it boots. |
| Charts say "require PostgreSQL" | `SENTINEL_DATABASE_URL` points at SQLite. Use the Supabase URL. |
| `401 invalid or missing API key` | Paste `SENTINEL_API_KEY` in Settings → Admin key. |
| Database getting large | Lower `SENTINEL_RETENTION_DAYS` (default 7 on Render). |
| "Send test email" fails with 502 | Wrong Brevo API key, or `SENTINEL_EMAIL_FROM` is not a verified sender in Brevo. |
| Test email never arrives | Check the spam folder; Brevo's dashboard → Logs shows every send. |
