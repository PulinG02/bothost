import os
import sys
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="NpcHosting")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BOTS_DIR  = Path("uploaded_bots")
DATA_FILE = Path("bots_data.json")   # ← persistent storage
BOTS_DIR.mkdir(exist_ok=True)

# In-memory runtime state (NOT saved to disk)
processes: Dict[str, subprocess.Popen] = {}
logs:      Dict[str, list]             = {}

MAX_LOG_LINES = 200


# ─── Persistence helpers ───────────────────────────────────────────────────────

def load_bots() -> Dict[str, dict]:
    """Load bot registry from disk."""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {}

def save_bots(bots: dict):
    """Save bot registry to disk (skip runtime-only fields)."""
    safe = {}
    for bid, b in bots.items():
        safe[bid] = {k: v for k, v in b.items()
                     if k not in ("uptime_start", "uptime_end")}
        safe[bid]["status"] = "stopped"   # always mark stopped on save
    DATA_FILE.write_text(json.dumps(safe, indent=2))

# Load on startup
bots: Dict[str, dict] = load_bots()


# ─── Utility ──────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def append_log(bot_id: str, line: str):
    logs.setdefault(bot_id, [])
    logs[bot_id].append(f"[{ts()}] {line}")
    if len(logs[bot_id]) > MAX_LOG_LINES:
        logs[bot_id] = logs[bot_id][-MAX_LOG_LINES:]

def stream_output(bot_id: str, proc: subprocess.Popen):
    def read_stream(stream, prefix=""):
        try:
            for line in iter(stream.readline, ""):
                if line:
                    append_log(bot_id, prefix + line.rstrip())
        except Exception:
            pass

    threading.Thread(target=read_stream, args=(proc.stdout,),        daemon=True).start()
    threading.Thread(target=read_stream, args=(proc.stderr, "ERR: "), daemon=True).start()

    def wait_proc():
        proc.wait()
        if bot_id in bots and bots[bot_id]["status"] == "running":
            bots[bot_id]["status"] = "stopped"
            save_bots(bots)
            append_log(bot_id, f"🛑 Process exited (code: {proc.returncode})")

    threading.Thread(target=wait_proc, daemon=True).start()

def get_uptime(bot_id: str) -> str:
    b = bots.get(bot_id)
    if not b or b["status"] != "running":
        return "—"
    elapsed = int(time.time() - b.get("uptime_start", time.time()))
    d, r = divmod(elapsed, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d: return f"{d}d {h}h {m}m"
    if h: return f"{h}h {m}m"
    return f"{m}m {s}s"

def get_memory_mb(bot_id: str) -> float:
    proc = processes.get(bot_id)
    if not proc or proc.poll() is not None:
        return 0.0
    try:
        with open(f"/proc/{proc.pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return 0.0

def get_cpu_percent(bot_id: str) -> float:
    proc = processes.get(bot_id)
    if not proc or proc.poll() is not None:
        return 0.0
    try:
        result = subprocess.run(
            ["ps", "-p", str(proc.pid), "-o", "%cpu", "--no-headers"],
            capture_output=True, text=True, timeout=2
        )
        val = result.stdout.strip()
        return float(val) if val else 0.0
    except Exception:
        return 0.0


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path("templates/index.html")
    if html_path.exists():
        return html_path.read_text()
    return "<h1>NpcHosting running — frontend not found</h1>"


@app.get("/api/bots")
def list_bots():
    return [
        {
            "id":     bid,
            "name":   b["name"],
            "file":   b["file"],
            "status": b["status"],
            "token":  b["token_masked"],
            "uptime": get_uptime(bid),
            "memory": get_memory_mb(bid),
            "cpu":    get_cpu_percent(bid),
        }
        for bid, b in bots.items()
    ]


@app.get("/api/bots/{bot_id}/logs")
def get_logs(bot_id: str, since: int = 0):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    all_logs = logs.get(bot_id, [])
    return {"logs": all_logs[since:], "total": len(all_logs)}


@app.post("/api/bots/deploy")
async def deploy_bot(
    name:  str        = Form(...),
    token: str        = Form(...),
    file:  UploadFile = File(...)
):
    if not file.filename.endswith(".py"):
        raise HTTPException(400, "Only .py files allowed")

    bot_id  = str(uuid.uuid4())[:8]
    bot_dir = BOTS_DIR / bot_id
    bot_dir.mkdir(exist_ok=True)

    file_path = bot_dir / file.filename
    content   = await file.read()
    file_path.write_bytes(content)

    parts  = token.split(":")
    masked = (parts[0][:6] + "****:" + parts[1][:4] + "****") if len(parts) == 2 else token[:8] + "****"

    bots[bot_id] = {
        "name":         name,
        "file":         file.filename,
        "file_path":    str(file_path.resolve()),
        "token":        token,
        "token_masked": masked,
        "status":       "stopped",
    }
    save_bots(bots)   # ← persist immediately

    logs[bot_id] = []
    append_log(bot_id, f"📦 {file.filename} uploaded ({len(content)} bytes)")
    append_log(bot_id, f"🔑 Token configured")
    append_log(bot_id, f"✅ Bot registered — starting now…")

    _start_bot(bot_id)
    return {"id": bot_id, "message": "Deployed"}


@app.post("/api/bots/{bot_id}/start")
def start_bot(bot_id: str):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    if bots[bot_id]["status"] == "running":
        return {"message": "Already running"}
    _start_bot(bot_id)
    return {"message": "Started"}


@app.post("/api/bots/{bot_id}/stop")
def stop_bot(bot_id: str):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    _stop_bot(bot_id)
    return {"message": "Stopped"}


@app.post("/api/bots/{bot_id}/restart")
def restart_bot(bot_id: str):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    _stop_bot(bot_id)
    time.sleep(0.5)
    _start_bot(bot_id)
    return {"message": "Restarted"}


@app.delete("/api/bots/{bot_id}")
def delete_bot(bot_id: str):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    _stop_bot(bot_id)

    import shutil
    bot_dir = BOTS_DIR / bot_id
    if bot_dir.exists():
        shutil.rmtree(bot_dir)

    bots.pop(bot_id, None)
    logs.pop(bot_id, None)
    processes.pop(bot_id, None)
    save_bots(bots)   # ← persist deletion
    return {"message": "Deleted"}


@app.get("/api/bots/{bot_id}/download")
def download_bot(bot_id: str):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    file_path = Path(bots[bot_id]["file_path"])
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(
        path=str(file_path),
        filename=bots[bot_id]["file"],
        media_type="text/x-python"
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _start_bot(bot_id: str):
    b         = bots[bot_id]
    abs_path  = Path(b["file_path"]).resolve()
    env       = os.environ.copy()
    env["BOT_TOKEN"]          = b["token"]
    env["TELEGRAM_BOT_TOKEN"] = b["token"]

    try:
        proc = subprocess.Popen(
            [sys.executable, str(abs_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
            env=env,
            cwd=str(abs_path.parent),
        )
        processes[bot_id]              = proc
        bots[bot_id]["status"]         = "running"
        bots[bot_id]["uptime_start"]   = time.time()
        save_bots(bots)               # ← persist running status
        append_log(bot_id, f"▶ Started (PID: {proc.pid})")
        stream_output(bot_id, proc)
    except Exception as e:
        bots[bot_id]["status"] = "stopped"
        save_bots(bots)
        append_log(bot_id, f"❌ Failed to start: {e}")


def _stop_bot(bot_id: str):
    proc = processes.get(bot_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
    bots[bot_id]["status"] = "stopped"
    save_bots(bots)        # ← persist stopped status
    append_log(bot_id, "🛑 Bot stopped")
    processes.pop(bot_id, None)


# ─── Auto-restart bots on server startup ──────────────────────────────────────

@app.on_event("startup")
def auto_restart_bots():
    """Re-launch all bots that were running before the server restarted."""
    restarted = 0
    for bot_id, b in list(bots.items()):
        file_path = Path(b.get("file_path", ""))
        if not file_path.exists():
            append_log(bot_id, "⚠️ File missing — skipped on restart")
            continue
        logs.setdefault(bot_id, [])
        append_log(bot_id, "🔄 Server restarted — auto-resuming bot…")
        _start_bot(bot_id)
        restarted += 1
    print(f"[NpcHosting] Auto-restarted {restarted} bot(s) from saved data.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
