# JKT48 VC Hybrid Monitor — starter

Hybrid monitoring **framework** for the JKT48 EX2F12 VC page. **No verified public stock API has been identified**, and this project does not bypass login, paywalls, bot protection, or extract hidden site endpoints. The included sample is demonstrative only. For real data, connect a legitimate authorized JSON export/API. Avoid sharing session cookies or tokens.

## Architecture

- Railway (one instance): FastAPI dashboard + SQLite on persistent Railway volume + optional cloud polling of **configured authorized JSON source** + Discord webhook. Dashboard Basic Auth.
- Windows terminal: `local_collector.py` reads authorized local JSON file or URL, sends authenticated snapshots to Railway.
- Both collectors write into one central table keyed by stable `id`. Changes are computed centrally (and Discord alerted once per change); first snapshots are quiet by default. Cloud and local need the **same semantic item IDs** and consistent values. Last-arriving report wins. Disable cloud polling if its feed differs or lags behind local.

## 1. Create a NEW Railway project (leave existing project untouched)

1. Extract this zip to a NEW directory and push the files to a NEW GitHub repo (never commit `.env`).
2. Railway → New Project → Deploy from GitHub repo → choose this new repo. Dockerfile auto-detected.
3. Railway → Service → Variables (insert your own random long secrets):

```
INGEST_TOKEN=<long-random-secret>
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=<long-random-password>
DB_PATH=/app/data/vc.db
DISCORD_WEBHOOK_URL=<your-discord-webhook-url>
CLOUD_POLL_ENABLED=false
POLL_SECONDS=60
```

4. Railway service → add **Volume** mounted at `/app/data` for SQLite persistence. Set **replicas=1**. Do not point two independently deployed instances at one SQLite file.
5. Service → Settings → Networking → Generate Domain. Open generated Railway URL; browser asks for dashboard username/password.
6. Setup Discord: Server Settings → Integrations → Webhooks → New Webhook; copy secret URL into Railway Variables only. Alerts occur on changes, not baseline.

## 2. Windows local collector

Install Python 3.10+. In extracted folder make a `.env` file (do NOT commit):

```
RAILWAY_URL=https://YOUR-RAILWAY-DOMAIN.up.railway.app
INGEST_TOKEN=<same-as-Railway-INGEST_TOKEN>
LOCAL_SOURCE_FILE=vc-sample.json
COLLECTOR_NAME=windows-local
POLL_SECONDS=60
```

Right-click `run-local.ps1` → Run with PowerShell, or from terminal:

```
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

The sample records a **demo placeholder with unknown stock**. It does not monitor JKT48. For real use, point `LOCAL_SOURCE_FILE` to an updated authorized JSON export, or set `LOCAL_SOURCE_URL` for a JSON API you have permission to access. Keep terminal running (or later configure Task Scheduler).

## 3. Activate cloud collector (only once source is verified)

Set in Railway Variables:

```
CLOUD_POLL_ENABLED=true
CLOUD_SOURCE_URL=https://your-authorized-json-feed.example/api/vc
CLOUD_SOURCE_BEARER=<optional-source-token>
```

Do NOT put the JKT48 HTML purchase URL into `CLOUD_SOURCE_URL` because the collector expects JSON and the page requires login. Cloud collector errors appear on dashboard; no stock changes are invented on failed fetch.

## JSON data contract

Both sources must return:

```json
{"items":[{"id":"unique-stable-session-member-id","member":"Member Name","session":"VC Session 1","stock":8,"status":"available"}]}
```

`stock` can be `null` when unknown; do not map unknown to zero. `status` is an arbitrary string such as `available`, `sold_out`, or `unknown`. A missing item is not automatically interpreted as sold out. Use stable IDs across sources.

### Security, limits & cautions

- NEVER publish `.env`, session cookies, Discord webhook URLs, or tokens. Dashboard is Basic Auth over Railway HTTPS; use strong credentials.
- Public `/health` exposes only health. `/api/state` and `/` require dashboard Basic Auth. `/api/ingest` requires bearer token.
- Data changes are only assessed on new valid snapshots. Persistent volume is required for reliable de-duplication across restarts.
- Concurrent local/cloud reports of stale/different values can produce oscillating alerts. Use a single authoritative feed or disable cloud polling until the sources agree.
- Discord requests may fail; failed sends are printed to logs rather than retried from a durable queue. This is a starter, not guaranteed-delivery notification infrastructure.
- No automatic deletion/expiry of missing inventory records. Check collector freshness to detect stale data.
- Avoid aggressive polling or unauthorized collection; comply with source terms and usage limits.
