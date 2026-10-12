"""Hybrid VC monitor. Only processes JSON obtained from authorized sources."""
import asyncio, hmac, json, os, sqlite3, time, threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn

app = FastAPI(title="JKT48 VC Hybrid Monitor", docs_url=None, redoc_url=None)
security = HTTPBasic(auto_error=False)
DB_PATH = os.getenv("DB_PATH", "./data/vc.db")
lock = threading.RLock()

def iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory=sqlite3.Row
    return db

def init_db():
    with get_db() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS inventory (item_id TEXT PRIMARY KEY, member TEXT NOT NULL, session TEXT NOT NULL, stock INTEGER, status TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, member TEXT, session TEXT, previous_stock INTEGER, stock INTEGER, previous_status TEXT, status TEXT, source TEXT, created_at TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS collectors (name TEXT PRIMARY KEY, last_seen TEXT, last_ok TEXT, last_error TEXT, item_count INTEGER DEFAULT 0)")

def auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    u=os.getenv("DASHBOARD_USER", "admin")
    p=os.getenv("DASHBOARD_PASSWORD", "")
    if not p or credentials is None or not (hmac.compare_digest(credentials.username,u) and hmac.compare_digest(credentials.password,p)):
        raise HTTPException(status_code=401,detail="Authentication required",headers={"WWW-Authenticate": 'Basic realm="VC Monitor"'})

def token_auth(request: Request):
    expected=os.getenv("INGEST_TOKEN", "")
    provided=request.headers.get("Authorization", "")
    if not expected or not hmac.compare_digest(provided,"Bearer "+expected):
        raise HTTPException(status_code=401,detail="Invalid collector token")

def parse_items(body: Any):
    if not isinstance(body,dict) or not isinstance(body.get("items"),list):
        raise ValueError('Expected JSON object with "items" list')
    if len(body["items"])>1000: raise ValueError("Too many items")
    parsed=[]; ids=set()
    for item in body["items"]:
        if not isinstance(item,dict): raise ValueError("Each item must be an object")
        id_=str(item.get("id", "")).strip()[:160]
        member=str(item.get("member", "")).strip()[:160]
        session=str(item.get("session", "")).strip()[:160]
        status=str(item.get("status", "unknown")).strip().lower()[:80]
        stock=item.get("stock")
        if isinstance(stock,bool) or (stock is not None and (not isinstance(stock,int) or stock<0)):
            raise ValueError("stock must be nonnegative integer or null")
        if not id_ or not member or not session or id_ in ids: raise ValueError("Missing or duplicate id/member/session")
        ids.add(id_); parsed.append((id_,member,session,stock,status))
    return parsed

def record_error(source: str, msg: str):
    with lock, get_db() as db:
        db.execute("INSERT INTO collectors(name,last_seen,last_error) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen,last_error=excluded.last_error",(source,iso(),msg[:300]))

def store(source: str, items: list):
    changes=[]; now=iso()
    with lock, get_db() as db:
        for id_,member,session,stock,status in items:
            prev=db.execute("SELECT * FROM inventory WHERE item_id=?",(id_,)).fetchone()
            # Last received valid report wins. Null stock indicates unknown, not zero.
            if prev and (prev["stock"]!=stock or prev["status"]!=status):
                changes.append({"id":id_,"member":member,"session":session,"before":prev["stock"],"after":stock,"before_status":prev["status"],"status":status})
                db.execute("INSERT INTO events(item_id,member,session,previous_stock,stock,previous_status,status,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(id_,member,session,prev["stock"],stock,prev["status"],status,source,now))
            elif not prev and os.getenv("ALERT_INITIAL","false").lower()=="true":
                changes.append({"id":id_,"member":member,"session":session,"before":None,"after":stock,"before_status":"new","status":status})
            db.execute("INSERT INTO inventory(item_id,member,session,stock,status,updated_at,source) VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET member=excluded.member,session=excluded.session,stock=excluded.stock,status=excluded.status,updated_at=excluded.updated_at,source=excluded.source",(id_,member,session,stock,status,now,source))
        db.execute("INSERT INTO collectors(name,last_seen,last_ok,last_error,item_count) VALUES(?,?,?,NULL,?) ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen,last_ok=excluded.last_ok,last_error=NULL,item_count=excluded.item_count",(source,now,now,len(items)))
    return changes

async def discord(changes):
    url=os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url or not changes: return
    async with httpx.AsyncClient(timeout=12) as client:
        for i in range(0,len(changes),8):
            rows=changes[i:i+8]
            description="\n".join(f"**{c['member']}** · {c['session']}\n{c['before'] if c['before'] is not None else 'unknown'} → **{c['after'] if c['after'] is not None else 'unknown'}** · {c['before_status']} → {c['status']}" for c in rows)
            payload={"username":"JKT48 VC Monitor", "embeds":[{"title":"VC inventory changed", "description":description[:3800],"url":"https://jkt48.com/purchase/exclusive?code=EX2F12","color":5763719,"timestamp":iso()}], "allowed_mentions":{"parse":[]}}
            try:
                r=await client.post(url,json=payload)
                r.raise_for_status()
            except Exception as exc:
                print("Discord delivery failure:",str(exc)[:160],flush=True)

@app.post("/api/ingest")
async def ingest(req: Request, _=Depends(token_auth)):
    try:
        body=await req.json()
        items=parse_items(body)
        source=str(body.get("collector","local"))[:80]
        if not source or source.strip() != source: raise ValueError("Invalid collector")
        changes=store(source,items)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    await discord(changes)
    return {"ok":True,"items":len(items),"changes":len(changes),"time":iso()}

@app.get("/api/state")
def state(_=Depends(auth)):
    with lock,get_db() as db:
        inventory=[dict(r) for r in db.execute("SELECT * FROM inventory ORDER BY member,session")]
        events=[dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")]
        collectors=[dict(r) for r in db.execute("SELECT * FROM collectors ORDER BY name")]
    return {"inventory":inventory,"events":events,"collectors":collectors,"server_time":iso()}

@app.get("/health")
def health(): return {"ok":True,"time":iso()}

@app.get("/",response_class=HTMLResponse)
def index(_=Depends(auth)):
    return Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")

async def cloud_loop():
    await asyncio.sleep(3)
    while True:
        url=os.getenv("CLOUD_SOURCE_URL", "").strip()
        if url and os.getenv("CLOUD_POLL_ENABLED","false").lower()=="true":
            try:
                headers={"Accept":"application/json"}
                if os.getenv("CLOUD_SOURCE_BEARER"):
                    headers["Authorization"]="Bearer "+os.environ["CLOUD_SOURCE_BEARER"]
                async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
                    response=await client.get(url,headers=headers)
                    response.raise_for_status()
                    items=parse_items(response.json())
                changes=store("cloud",items)
                await discord(changes)
            except Exception as exc:
                record_error("cloud",str(exc))
        await asyncio.sleep(max(30,int(os.getenv("POLL_SECONDS","60"))))

@app.on_event("startup")
async def startup():
    init_db()
    app.state.collector_task=asyncio.create_task(cloud_loop())

@app.on_event("shutdown")
async def shutdown():
    app.state.collector_task.cancel()

if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))
