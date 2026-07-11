import os
import sys
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="BotHost")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BOTS_DIR = Path("uploaded_bots")
BOTS_DIR.mkdir(exist_ok=True)

# In-memory store: { bot_id: { ...info } }
bots: Dict[str, dict] = {}
# Running processes: { bot_id: subprocess.Popen }
processes: Dict[str, subprocess.Popen] = {}
# Log buffer: { bot_id: [lines] }
logs: Dict[str, list] = {}

MAX_LOG_LINES = 200


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(bot_id: str, line: str):
    if bot_id not in logs:
        logs[bot_id] = []
    logs[bot_id].append(f"[{ts()}] {line}")
    if len(logs[bot_id]) > MAX_LOG_LINES:
        logs[bot_id] = logs[bot_id][-MAX_LOG_LINES:]


def stream_output(bot_id: str, proc: subprocess.Popen):
    """Read stdout+stderr from process and store in log buffer."""
    def read_stream(stream, prefix=""):
        try:
            for line in iter(stream.readline, ""):
                if line:
                    append_log(bot_id, prefix + line.rstrip())
        except Exception:
            pass

    t1 = threading.Thread(target=read_stream, args=(proc.stdout,), daemon=True)
    t2 = threading.Thread(target=read_stream, args=(proc.stderr, "ERR: "), daemon=True)
    t1.start()
    t2.start()

    def wait_proc():
        proc.wait()
        if bot_id in bots:
            if bots[bot_id]["status"] == "running":
                bots[bot_id]["status"] = "stopped"
                bots[bot_id]["uptime_end"] = time.time()
                append_log(bot_id, "🛑 Process exited (code: {})".format(proc.returncode))

    threading.Thread(target=wait_proc, daemon=True).start()


def get_uptime(bot_id: str) -> str:
    b = bots.get(bot_id)
    if not b or b["status"] != "running":
        return "—"
    elapsed = int(time.time() - b["uptime_start"])
    d, r = divmod(elapsed, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def get_memory_mb(bot_id: str) -> float:
    proc = processes.get(bot_id)
    if not proc or proc.poll() is not None:
        return 0.0
    try:
        import resource
        # Try reading from /proc (Linux only)
        with open(f"/proc/{proc.pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024, 1)
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
    return "<h1>BotHost running — frontend not found</h1>"


@app.get("/api/bots")
def list_bots():
    result = []
    for bid, b in bots.items():
        result.append({
            "id": bid,
            "name": b["name"],
            "file": b["file"],
            "status": b["status"],
            "token": b["token_masked"],
            "uptime": get_uptime(bid),
            "memory": get_memory_mb(bid),
            "cpu": get_cpu_percent(bid),
        })
    return result


@app.get("/api/bots/{bot_id}/logs")
def get_logs(bot_id: str, since: int = 0):
    if bot_id not in bots:
        raise HTTPException(404, "Bot not found")
    all_logs = logs.get(bot_id, [])
    return {"logs": all_logs[since:], "total": len(all_logs)}


@app.post("/api/bots/deploy")
async def deploy_bot(
    name: str = Form(...),
    token: str = Form(...),
    file: UploadFile = File(...)
):
    if not file.filename.endswith(".py"):
        raise HTTPException(400, "Only .py files allowed")

    bot_id = str(uuid.uuid4())[:8]
    bot_dir = BOTS_DIR / bot_id
    bot_dir.mkdir(exist_ok=True)

    # Save file
    file_path = bot_dir / file.filename
    content = await file.read()
    file_path.write_bytes(content)

    # Mask token
    parts = token.split(":")
    if len(parts) == 2:
        masked = parts[0][:6] + "****:" + parts[1][:4] + "****"
    else:
        masked = token[:8] + "****"

    # Store bot info
    bots[bot_id] = {
        "name": name,
        "file": file.filename,
        "file_path": str(file_path.resolve()),
        "token": token,
        "token_masked": masked,
        "status": "stopped",
        "uptime_start": None,
        "uptime_end": None,
    }
    logs[bot_id] = []
    append_log(bot_id, f"📦 {file.filename} uploaded ({len(content)} bytes)")
    append_log(bot_id, f"🔑 Token configured")
    append_log(bot_id, f"✅ Bot registered — click Start to run")

    # Auto-start
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

    # Remove files
    import shutil
    bot_dir = BOTS_DIR / bot_id
    if bot_dir.exists():
        shutil.rmtree(bot_dir)

    bots.pop(bot_id, None)
    logs.pop(bot_id, None)
    processes.pop(bot_id, None)
    return {"message": "Deleted"}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _start_bot(bot_id: str):
    b = bots[bot_id]
    file_path = b["file_path"]
    token = b["token"]

    env = os.environ.copy()
    env["BOT_TOKEN"] = token
    env["TELEGRAM_BOT_TOKEN"] = token

    try:
        abs_path = Path(file_path).resolve()
        proc = subprocess.Popen(
            [sys.executable, str(abs_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=str(abs_path.parent),
        )
        processes[bot_id] = proc
        bots[bot_id]["status"] = "running"
        bots[bot_id]["uptime_start"] = time.time()
        append_log(bot_id, f"▶ Started (PID: {proc.pid})")
        stream_output(bot_id, proc)
    except Exception as e:
        bots[bot_id]["status"] = "stopped"
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
    bots[bot_id]["uptime_end"] = time.time()
    append_log(bot_id, "🛑 Bot stopped")
    processes.pop(bot_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
