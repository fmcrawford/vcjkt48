"""Windows/Linux agent. Reads authorized JSON URL or local JSON export and posts to Railway."""
import json,os,time,urllib.request,urllib.error
from pathlib import Path

def load_env(path=".env"):
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k,v=line.split("=",1);os.environ.setdefault(k.strip(),v.strip())

def read_items():
    endpoint=os.getenv("LOCAL_SOURCE_URL","")
    if endpoint:
        headers={"Accept":"application/json"}
        if os.getenv("LOCAL_SOURCE_BEARER"): headers["Authorization"]="Bearer "+os.environ["LOCAL_SOURCE_BEARER"]
        with urllib.request.urlopen(urllib.request.Request(endpoint,headers=headers),timeout=20) as r:
            return json.load(r)
    path=os.getenv("LOCAL_SOURCE_FILE","vc-sample.json")
    return json.loads(Path(path).read_text(encoding="utf8"))

def cycle():
    base=os.environ["RAILWAY_URL"].rstrip("/")
    data=read_items()
    if not isinstance(data,dict) or not isinstance(data.get("items"),list): raise ValueError("Source must be {'items': [...]}")
    data["collector"]=os.getenv("COLLECTOR_NAME","windows-local")
    body=json.dumps(data).encode()
    req=urllib.request.Request(base+"/api/ingest",data=body,headers={"Authorization":"Bearer "+os.environ["INGEST_TOKEN"],"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=25) as res:
        return json.load(res)

if __name__=="__main__":
    load_env()
    for key in ["RAILWAY_URL","INGEST_TOKEN"]:
        if not os.getenv(key): raise SystemExit("Missing "+key+" in environment/.env")
    print("Local VC collector running. CTRL+C to stop",flush=True)
    while True:
        try: print(time.strftime("%Y-%m-%d %H:%M:%S"),cycle(),flush=True)
        except Exception as e: print("Collector ERROR:",str(e)[:220],flush=True)
        time.sleep(max(30,int(os.getenv("POLL_SECONDS","60"))))
