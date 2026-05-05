"""
1x Dashboard — FastAPI Backend
=================================
Dedicated dashboard for the 1x client project.
Hardcoded project: 2a813775-341b-4408-954d-83f7dab3e840

Overview Metrics (date-range aware):
- Number of Annotators
- Number of Tasks Annotated
- Total Annotation Time
- Video Duration Annotated  ← from get_task_actions / get_editor_logs (same as get_video_duration.py)
- Time per Task
- Number of Reviewers
- Number of Tasks Reviewed
- Hours Reviewed
- Ratio = Total Annotation Time / Video Duration

⛔ READ-ONLY — no writes to Encord.
"""

import os
import time
import hashlib
# sqlite3 removed — using PostgreSQL via psycopg2
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# ─── Load .env ───
load_dotenv()

SSH_KEY_PATH  = os.getenv("ENCORD_SSH_KEY_PATH", "")
ENCORD_DOMAIN = os.getenv("ENCORD_DOMAIN", "https://api.encord.com")

# Hardcoded for 1x client
PROJECT_HASH_1X = "2a813775-341b-4408-954d-83f7dab3e840"

LABEL_ROW_BATCH = 250   # max data_hashes per list_label_rows_v2 call

# ─── Encord Client (lazy init) ───
_user_client = None


def get_encord_client():
    global _user_client
    if _user_client is not None:
        return _user_client
    if not SSH_KEY_PATH:
        raise ValueError("ENCORD_SSH_KEY_PATH not set in .env file.")
    if not Path(SSH_KEY_PATH).exists():
        raise FileNotFoundError(f"SSH key not found at: {SSH_KEY_PATH}")
    from encord import EncordUserClient
    _user_client = EncordUserClient.create_with_ssh_private_key(
        ssh_private_key_path=SSH_KEY_PATH,
        domain=ENCORD_DOMAIN,
    )
    print(f"  ✓ Connected to Encord ({ENCORD_DOMAIN})")
    return _user_client


# ─── Helpers ───

def get_duration_seconds(lr) -> float:
    """
    Exact copy of get_video_duration.py's fallback chain:
        lr.duration → frames / fps → 0.0
    """
    dur = getattr(lr, "duration", None)
    if dur is not None and float(dur) > 0:
        return float(dur)
    fps    = getattr(lr, "fps", None) or getattr(lr, "frames_per_second", None)
    frames = getattr(lr, "number_of_frames", None)
    if fps and frames and float(fps) > 0:
        return float(frames) / float(fps)
    return 0.0


def find_annotate_stage_uuids(project) -> list:
    """Return UUID(s) of all Annotate-type workflow stages."""
    uuids = []
    for stage in project.workflow.stages:
        stype = str(getattr(stage, "stage_type", "")).upper()
        title = (getattr(stage, "title", "") or "").lower()
        if "ANNOTATION" in stype or "ANNOTATE" in stype or title in ("annotate", "annotation"):
            uuids.append(stage.uuid)
    return uuids


def fetch_label_rows_batched(project, data_hashes: list) -> list:
    """Fetch label rows in batches to avoid URL-size limits."""
    rows = []
    for i in range(0, len(data_hashes), LABEL_ROW_BATCH):
        batch = data_hashes[i: i + LABEL_ROW_BATCH]
        rows.extend(project.list_label_rows_v2(data_hashes=batch))
    return rows


def format_seconds(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"


def format_name_from_email(email: str) -> str:
    local = email.split("@")[0]
    parts = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(p.capitalize() for p in parts) if parts else email


def get_initials(name: str) -> str:
    if not name:
        return "??"
    if "@" in name:
        name = name.split("@")[0]
    parts = name.replace("_", " ").replace("-", " ").replace(".", " ").split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


# ─── TTL Cache ───
_cache: dict = {}
CACHE_TTL = 14400  # 4 hours


def _cache_key(project_hash: str, start: str, end: str) -> str:
    return hashlib.md5(f"{project_hash}|{start}|{end}".encode()).hexdigest()


def _get_cached(k: str):
    e = _cache.get(k)
    if e and (time.time() - e["ts"]) < CACHE_TTL:
        return e["data"]
    return None


def _set_cache(k: str, data):
    _cache[k] = {"data": data, "ts": time.time()}


# ─── FastAPI App ───
app = FastAPI(title="1x Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── PostgreSQL: curated_metrics + projects tables ───
import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL", "")

def _db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def _query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Helper: run a query and return results as list of dicts."""
    conn = _db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    result = None
    if fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()
    if commit:
        conn.commit()
    cur.close()
    conn.close()
    return result

def _exec(sql, params=(), commit=True):
    """Helper: execute a write query."""
    conn = _db()
    cur = conn.cursor()
    cur.execute(sql, params)
    if commit:
        conn.commit()
    cur.close()
    conn.close()

def _init_db():
    conn = _db()
    cur = conn.cursor()
    # Projects registry
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            project_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Curated daily metrics
    cur.execute("""
        CREATE TABLE IF NOT EXISTS curated_metrics (
            id SERIAL PRIMARY KEY,
            project_hash TEXT NOT NULL,
            date TEXT NOT NULL,
            active_annotators INTEGER DEFAULT 0,
            tasks INTEGER DEFAULT 0,
            tpt_seconds REAL DEFAULT 0,
            ann_time_seconds REAL DEFAULT 0,
            vid_duration_seconds REAL DEFAULT 0,
            ratio REAL,
            notes TEXT DEFAULT '',
            custom_metrics TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(project_hash, date)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("  ✓ PostgreSQL: projects + curated_metrics tables ready")

_init_db()

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


from fastapi.responses import HTMLResponse

@app.get("/")
async def root():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.get("/static/{filename:path}")
async def serve_static(filename: str):
    """Serve static files with no-cache headers to avoid stale Content-Length."""
    file_path = FRONTEND_DIR / filename
    if not file_path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    content = file_path.read_bytes()
    suffix = file_path.suffix
    mime = {
        ".css": "text/css",
        ".js":  "application/javascript",
        ".html": "text/html",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(suffix, "application/octet-stream")
    from starlette.responses import Response
    return Response(content=content, media_type=mime,
                    headers={"Cache-Control": "no-store"})


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={}, status_code=204)


@app.get("/admin")
async def admin_page():
    html = (FRONTEND_DIR / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.get("/client")
async def client_page():
    html = (FRONTEND_DIR / "client.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# ════════════════════════════════════════════════
# PROJECTS CRUD
# ════════════════════════════════════════════════

@app.get("/api/projects")
def list_projects():
    """List all saved projects."""
    rows = _query("SELECT * FROM projects ORDER BY name ASC", fetchall=True) or []
    return [{"id": r["id"], "name": r["name"], "project_hash": r["project_hash"], "created_at": str(r["created_at"])} for r in rows]


@app.post("/api/projects")
def add_project(payload: dict = Body(...)):
    """Add a new project."""
    name = (payload.get("name") or "").strip()
    ph = (payload.get("project_hash") or "").strip()
    if not name or not ph:
        return JSONResponse(status_code=400, content={"error": "name and project_hash are required"})
    try:
        _exec("INSERT INTO projects (name, project_hash) VALUES (%s, %s)", (name, ph))
    except psycopg2.errors.UniqueViolation:
        return JSONResponse(status_code=409, content={"error": "Project hash already exists"})
    row = _query("SELECT * FROM projects WHERE project_hash = %s", (ph,), fetchone=True)
    return {"status": "ok", "id": row["id"], "name": name, "project_hash": ph}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    """Remove a project."""
    _exec("DELETE FROM projects WHERE id = %s", (project_id,))
    return {"status": "deleted", "id": project_id}


# ════════════════════════════════════════════════
# CURATED METRICS CRUD
# ════════════════════════════════════════════════

@app.get("/api/curated")
def list_curated(
    project_hash: str = Query(default=None),
    date_from: str = Query(default=None),
    date_to: str = Query(default=None),
):
    """List all curated daily entries for a project within a date range."""
    ph = (project_hash or "").strip() or PROJECT_HASH_1X
    q = "SELECT * FROM curated_metrics WHERE project_hash = %s"
    params = [ph]
    if date_from:
        q += " AND date >= %s"
        params.append(date_from)
    if date_to:
        q += " AND date <= %s"
        params.append(date_to)
    q += " ORDER BY date DESC"
    rows = _query(q, tuple(params), fetchall=True) or []
    import json as _json
    results = []
    for r in rows:
        custom = {}
        try:
            custom = _json.loads(r["custom_metrics"] or "{}")
        except Exception:
            pass
        results.append({
            "id": r["id"],
            "project_hash": r["project_hash"],
            "date": r["date"],
            "active_annotators": r["active_annotators"],
            "tasks": r["tasks"],
            "tpt_seconds": r["tpt_seconds"],
            "tpt_raw": format_seconds(r["tpt_seconds"] or 0),
            "ann_time_seconds": r["ann_time_seconds"],
            "ann_time_raw": format_seconds(r["ann_time_seconds"] or 0),
            "vid_duration_seconds": r["vid_duration_seconds"],
            "vid_duration_raw": format_seconds(r["vid_duration_seconds"] or 0),
            "ratio": r["ratio"],
            "notes": r["notes"] or "",
            "custom_metrics": custom,
            "updated_at": str(r["updated_at"]) if r["updated_at"] else "",
        })
    return results


@app.post("/api/curated")
def upsert_curated(payload: dict = Body(...)):
    """Create or update a curated daily entry. Uses UPSERT on (project_hash, date)."""
    ph = (payload.get("project_hash") or "").strip() or PROJECT_HASH_1X
    date = payload.get("date", "")
    if not date:
        return JSONResponse(status_code=400, content={"error": "date is required (YYYY-MM-DD)"})

    import json as _json
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    custom_json = _json.dumps(payload.get("custom_metrics", {}))
    _exec("""
        INSERT INTO curated_metrics
            (project_hash, date, active_annotators, tasks, tpt_seconds,
             ann_time_seconds, vid_duration_seconds, ratio, notes, custom_metrics,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(project_hash, date) DO UPDATE SET
            active_annotators = EXCLUDED.active_annotators,
            tasks = EXCLUDED.tasks,
            tpt_seconds = EXCLUDED.tpt_seconds,
            ann_time_seconds = EXCLUDED.ann_time_seconds,
            vid_duration_seconds = EXCLUDED.vid_duration_seconds,
            ratio = EXCLUDED.ratio,
            notes = EXCLUDED.notes,
            custom_metrics = EXCLUDED.custom_metrics,
            updated_at = EXCLUDED.updated_at
    """, (
        ph,
        date,
        payload.get("active_annotators", 0),
        payload.get("tasks", 0),
        payload.get("tpt_seconds", 0),
        payload.get("ann_time_seconds", 0),
        payload.get("vid_duration_seconds", 0),
        payload.get("ratio"),
        payload.get("notes", ""),
        custom_json,
        now, now,
    ))
    row = _query(
        "SELECT * FROM curated_metrics WHERE project_hash = %s AND date = %s", (ph, date), fetchone=True
    )
    return {"status": "ok", "id": row["id"], "date": date}


@app.put("/api/curated/{entry_id}")
def update_curated(entry_id: int, payload: dict = Body(...)):
    """Update a specific curated entry by ID."""
    import json as _json
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    custom_json = _json.dumps(payload.get("custom_metrics", {}))
    _exec("""
        UPDATE curated_metrics SET
            active_annotators = %s,
            tasks = %s,
            tpt_seconds = %s,
            ann_time_seconds = %s,
            vid_duration_seconds = %s,
            ratio = %s,
            notes = %s,
            custom_metrics = %s,
            updated_at = %s
        WHERE id = %s
    """, (
        payload.get("active_annotators", 0),
        payload.get("tasks", 0),
        payload.get("tpt_seconds", 0),
        payload.get("ann_time_seconds", 0),
        payload.get("vid_duration_seconds", 0),
        payload.get("ratio"),
        payload.get("notes", ""),
        custom_json,
        now,
        entry_id,
    ))
    return {"status": "ok", "id": entry_id}


@app.delete("/api/curated/{entry_id}")
def delete_curated(entry_id: int):
    """Delete a curated entry."""
    _exec("DELETE FROM curated_metrics WHERE id = %s", (entry_id,))
    return {"status": "deleted", "id": entry_id}


# ════════════════════════════════════════════════
# SDK PREVIEW (for admin panel)
# ════════════════════════════════════════════════

@app.get("/api/sdk-preview")
def sdk_preview(
    project_hash: str = Query(default=None),
    date_from: str = Query(default=None),
    date_to: str = Query(default=None),
):
    """
    Fetch SDK data for a date range and return daily breakdown.
    This is the preview data the admin sees before curating.
    """
    ph = (project_hash or "").strip() or PROJECT_HASH_1X
    if not date_from or not date_to:
        # Default: last 30 days
        dt_end = datetime.now(timezone.utc)
        dt_start = dt_end - timedelta(days=30)
    else:
        try:
            dt_start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            dt_end = datetime.strptime(date_to, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid date format"})

    try:
        client = get_encord_client()
        project = client.get_project(ph)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    try:
        # Reuse the daily breakdown logic from client-daily
        def _fetch_entries(): return list(project.list_time_spent(start=dt_start, end=dt_end))
        def _fetch_rows(): return list(project.list_label_rows_v2())

        with ThreadPoolExecutor(max_workers=2) as ex:
            time_entries = ex.submit(_fetch_entries).result()
            all_label_rows = ex.submit(_fetch_rows).result()

        lr_by_uuid = {str(getattr(lr, "data_uuid", "") or ""): lr for lr in all_label_rows}

        day_tasks = defaultdict(set)
        day_secs = defaultdict(float)
        day_users = defaultdict(set)
        day_vid = defaultdict(float)
        day_vseen = defaultdict(set)

        for entry in time_entries:
            wf = getattr(entry, "workflow_stage", None)
            st = str(getattr(wf, "stage_type", "")).upper() if wf else ""
            if "ANNOTATION" not in st:
                continue
            email = getattr(entry, "user_email", None) or "unknown"
            secs = float(getattr(entry, "time_spent_seconds", 0) or 0)
            uid = str(getattr(entry, "data_uuid", None) or "")
            ps = getattr(entry, "period_start_time", None)
            if not ps:
                continue
            try:
                dk = ps.date().isoformat() if hasattr(ps, "date") else str(ps)[:10]
            except Exception:
                continue
            day_secs[dk] += secs
            day_users[dk].add(email)
            if uid:
                day_tasks[dk].add(uid)
                if uid not in day_vseen[dk]:
                    day_vseen[dk].add(uid)
                    lr = lr_by_uuid.get(uid)
                    if lr:
                        day_vid[dk] += get_duration_seconds(lr)

        all_days = sorted(set(day_secs) | set(day_tasks))
        daily = []
        for dk in all_days:
            t = len(day_tasks[dk])
            a = day_secs[dk]
            v = day_vid[dk]
            daily.append({
                "date": dk,
                "active_annotators": len(day_users[dk]),
                "tasks": t,
                "tpt_seconds": round(a / t, 1) if t > 0 else 0,
                "tpt_raw": format_seconds(a / t) if t > 0 else "0s",
                "ann_time_seconds": round(a, 1),
                "ann_time_raw": format_seconds(a),
                "vid_duration_seconds": round(v, 1),
                "vid_duration_raw": format_seconds(v),
                "ratio": round(a / v, 2) if v > 0 else None,
            })

        return {
            "project_title": project.title,
            "project_hash": ph,
            "daily": daily,
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


# ════════════════════════════════════════════════
# CLIENT DAILY ENDPOINT (reads from curated_metrics)
# ════════════════════════════════════════════════
@app.get("/api/client-daily")
def get_client_daily(
    project_hash: str = Query(default=None),
    days: int = Query(default=30),
):
    """
    Client-facing endpoint. Reads from curated_metrics table.
    Only shows admin-approved data.
    """
    ph = (project_hash or "").strip() or PROJECT_HASH_1X
    dt_end = datetime.now(timezone.utc)
    dt_start = dt_end - timedelta(days=days)

    rows = _query(
        "SELECT * FROM curated_metrics WHERE project_hash = %s AND date >= %s AND date <= %s ORDER BY date ASC",
        (ph, dt_start.strftime("%Y-%m-%d"), dt_end.strftime("%Y-%m-%d")),
        fetchall=True,
    ) or []

    # Get project title from Encord (cached lightweight call)
    project_title = "Project Dashboard"
    try:
        client = get_encord_client()
        project = client.get_project(ph)
        project_title = project.title
    except Exception:
        pass

    daily = []
    for r in rows:
        daily.append({
            "date": r["date"],
            "tasks": r["tasks"] or 0,
            "ann_time_mins": round((r["ann_time_seconds"] or 0) / 60, 1),
            "ann_time_raw": format_seconds(r["ann_time_seconds"] or 0),
            "vid_duration_mins": round((r["vid_duration_seconds"] or 0) / 60, 1),
            "vid_duration_raw": format_seconds(r["vid_duration_seconds"] or 0),
            "tpt_mins": round((r["tpt_seconds"] or 0) / 60, 2),
            "tpt_raw": format_seconds(r["tpt_seconds"] or 0),
            "active_annotators": r["active_annotators"] or 0,
            "ratio": r["ratio"],
        })

    # ── All-time aggregation across ALL curated entries for this project ──
    agg = _query("""
        SELECT
            SUM(tasks) as total_tasks,
            SUM(ann_time_seconds) as total_ann_seconds,
            SUM(vid_duration_seconds) as total_vid_seconds,
            MAX(active_annotators) as max_annotators,
            COUNT(*) as day_count,
            AVG(tpt_seconds) as avg_tpt_seconds
        FROM curated_metrics WHERE project_hash = %s
    """, (ph,), fetchone=True)

    total_tasks = agg["total_tasks"] or 0
    total_ann = agg["total_ann_seconds"] or 0
    total_vid = agg["total_vid_seconds"] or 0
    avg_tpt = agg["avg_tpt_seconds"] or 0
    max_ann = agg["max_annotators"] or 0
    ratio = round(total_ann / total_vid, 2) if total_vid > 0 else None

    all_time = {
        "active_annotators": max_ann,
        "tasks": total_tasks,
        "tpt_seconds": round(avg_tpt, 1),
        "tpt_mins": round(avg_tpt / 60, 2) if avg_tpt else 0,
        "tpt_raw": format_seconds(avg_tpt),
        "ann_time_seconds": total_ann,
        "ann_time_mins": round(total_ann / 60, 1),
        "ann_time_raw": format_seconds(total_ann),
        "vid_duration_seconds": total_vid,
        "vid_duration_mins": round(total_vid / 60, 1),
        "vid_duration_raw": format_seconds(total_vid),
        "ratio": ratio,
        "day_count": agg["day_count"] or 0,
    }

    return {
        "project_title": project_title,
        "project_hash": ph,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "all_time": all_time,
        "daily": daily,
    }


# ════════════════════════════════════════════════
# MAIN DATA ENDPOINT
# ════════════════════════════════════════════════
@app.get("/api/1x-data")
def get_1x_data(
    project_hash: str = Query(default=None,  description="Encord project hash (defaults to 1x project)"),
    start_date:   str = Query(default=None,  description="Start date YYYY-MM-DD"),
    end_date:     str = Query(default=None,  description="End date YYYY-MM-DD"),
    days:         int = Query(default=90,    description="Days back if no date range"),
):
    """
    Fetch all 1x metrics from Encord — date-range aware.
    project_hash defaults to the 1x project but can be overridden via query param.
    """
    try:
        client = get_encord_client()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Auth failed: {str(e)}"})

    # Use provided hash or fall back to hardcoded 1x project
    ph = (project_hash or "").strip() or PROJECT_HASH_1X

    try:
        project = client.get_project(ph)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Could not load project '{ph}': {str(e)}"})  

    try:
        # ── Date Range ──────────────────────────────────────────────────
        if start_date and end_date:
            try:
                dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                dt_end   = datetime.strptime(end_date,   "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid date format. Use YYYY-MM-DD"})
        else:
            dt_end   = datetime.now(timezone.utc)
            dt_start = dt_end - timedelta(days=days)

        date_label = f"{dt_start.strftime('%d/%m/%Y')} to {dt_end.strftime('%d/%m/%Y')}"

        # ── Cache ──────────────────────────────────────────
        # Use project hash in cache key so different projects don't collide
        ck = hashlib.md5(f"{ph}|{dt_start}|{dt_end}".encode()).hexdigest()
        cached = _get_cached(ck)
        if cached:
            print("   Cache HIT — returning instantly")
            return cached

        t0 = time.time()
        print(f"  ⏳ Fetching 1x data from Encord [{date_label}] project={ph[:8]}...")

        # ── Parallel Fetch 1: time entries + label logs ─────────────────
        def fetch_time_entries():
            return list(project.list_time_spent(start=dt_start, end=dt_end))

        def fetch_label_logs():
            return list(project.get_label_logs(after=dt_start, before=dt_end))

        def fetch_all_label_rows():
            return list(project.list_label_rows_v2())

        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_time = executor.submit(fetch_time_entries)
            fut_logs = executor.submit(fetch_label_logs)
            fut_rows = executor.submit(fetch_all_label_rows)
            time_entries   = fut_time.result()
            label_logs_raw = fut_logs.result()
            all_label_rows = fut_rows.result()

        print(f"  ✓ Parallel fetch done in {time.time()-t0:.1f}s "
              f"(time_entries={len(time_entries)}, "
              f"label_logs={len(label_logs_raw)}, "
              f"label_rows={len(all_label_rows)})")

        # Build a uuid→label_row lookup for duration extraction
        lr_by_uuid  = {}
        lr_by_hash  = {}
        for lr in all_label_rows:
            dh  = str(getattr(lr, "data_hash", "") or "")
            uid = str(getattr(lr, "data_uuid", "") or "")
            if dh:
                lr_by_hash[dh]  = lr
            if uid:
                lr_by_uuid[uid] = lr

        # ── Group time entries by user + stage ──────────────────────────
        ann_data = defaultdict(lambda: {
            "time_seconds": 0,
            "data_uuids": set(),
            "dates": [],
        })
        rev_data = defaultdict(lambda: {
            "time_seconds": 0,
            "data_uuids": set(),
            "dates": [],
        })
        # Track data_uuids touched by annotators in this range
        annotated_uuids_in_range: set = set()

        for entry in time_entries:
            email      = getattr(entry, "user_email", None) or "unknown"
            seconds    = getattr(entry, "time_spent_seconds", 0) or 0
            data_uuid  = getattr(entry, "data_uuid", None)
            period_start = getattr(entry, "period_start_time", None)
            wf_stage   = getattr(entry, "workflow_stage", None)
            stage_type = str(getattr(wf_stage, "stage_type", "")).upper() if wf_stage else ""
            uuid_str   = str(data_uuid) if data_uuid else None

            if "ANNOTATION" in stage_type:
                ann_data[email]["time_seconds"] += seconds
                if uuid_str:
                    ann_data[email]["data_uuids"].add(uuid_str)
                    annotated_uuids_in_range.add(uuid_str)
                if period_start:
                    ann_data[email]["dates"].append(period_start)
            elif "REVIEW" in stage_type:
                rev_data[email]["time_seconds"] += seconds
                if uuid_str:
                    rev_data[email]["data_uuids"].add(uuid_str)
                if period_start:
                    rev_data[email]["dates"].append(period_start)

        # ── Video Duration — same logic as get_video_duration.py ────────
        # Priority 1: get_task_actions(SUBMIT) → exact submitted tasks
        # Priority 2: ann_submits data_hashes from label logs SUBMIT_TASK
        # Priority 3: annotated_uuids_in_range from time entries

        total_video_duration_seconds = 0.0
        videos_counted: set = set()

        submitted_uuids: set = set()   # uuids (from get_task_actions)
        submitted_hashes: set = set()  # data_hashes (from label logs SUBMIT_TASK)

        # We must process label logs first to get ann_submits data_hashes
        # (moved label log processing before this block)
        from encord.orm.label_log import Action

        ann_submits     = defaultdict(set)
        rev_approves    = defaultdict(set)
        rev_rejects     = defaultdict(set)
        dh_approved     = set()
        dh_rejected     = set()

        for log in label_logs_raw:
            email  = log.user_email
            dh     = log.data_hash
            action = log.action
            if action == Action.SUBMIT_TASK:
                ann_submits[email].add(dh)
                submitted_hashes.add(dh)  # collect all submitted data_hashes
            elif action == Action.APPROVE_TASK:
                rev_approves[email].add(dh)
                dh_approved.add(dh)
            elif action == Action.REJECT_TASK:
                rev_rejects[email].add(dh)
                dh_rejected.add(dh)

        # Try get_task_actions first (needs org-level key)
        try:
            from encord.orm.analytics import TaskActionType
            annotate_uuids = find_annotate_stage_uuids(project)
            print(f"  Fetching SUBMIT task actions (annotate stage count={len(annotate_uuids)})...")
            submit_actions = list(project.get_task_actions(
                after=dt_start,
                before=dt_end,
                action_type=TaskActionType.SUBMIT,
                workflow_stage_uuid=annotate_uuids if annotate_uuids else None,
            ))
            print(f"  ✓ {len(submit_actions)} SUBMIT actions in range")
            for a in submit_actions:
                uid = str(getattr(a, "data_unit_uuid", None) or "")
                if uid:
                    submitted_uuids.add(uid)
        except Exception as e:
            print(f"  ⚠ get_task_actions not available ({type(e).__name__})")

        # Sum video duration
        # Strategy A: use uuids from get_task_actions → lr_by_uuid lookup
        if submitted_uuids:
            for uid in submitted_uuids:
                if uid in videos_counted:
                    continue
                videos_counted.add(uid)
                lr = lr_by_uuid.get(uid)
                if lr:
                    total_video_duration_seconds += get_duration_seconds(lr)
            print(f"  ✓ Video duration (uuid path): {total_video_duration_seconds:.1f}s "
                  f"across {len(videos_counted)} videos")

        # Strategy B: use annotated_uuids_in_range from time entries
        if (not submitted_uuids or total_video_duration_seconds == 0) and annotated_uuids_in_range:
            print(f"  Using time-entry uuids ({len(annotated_uuids_in_range)} tasks) for duration...")
            total_video_duration_seconds = 0.0
            videos_counted = set()
            for uid in annotated_uuids_in_range:
                if uid in videos_counted:
                    continue
                videos_counted.add(uid)
                lr = lr_by_uuid.get(uid)
                if lr:
                    total_video_duration_seconds += get_duration_seconds(lr)
            print(f"  ✓ Video duration (time-entry path): {total_video_duration_seconds:.1f}s across {len(videos_counted)} videos")

        # Strategy C: final fallback — use data_hashes from label logs SUBMIT_TASK
        if total_video_duration_seconds == 0 and submitted_hashes:
            print(f"  Using label-log data_hashes ({len(submitted_hashes)} submitted tasks) for duration...")
            total_video_duration_seconds = 0.0
            videos_counted = set()
            for dh in submitted_hashes:
                if dh in videos_counted:
                    continue
                videos_counted.add(dh)
                lr = lr_by_hash.get(dh)
                if lr:
                    total_video_duration_seconds += get_duration_seconds(lr)
            print(f"  ✓ Video duration (hash path): {total_video_duration_seconds:.1f}s "
                  f"across {len(videos_counted)} videos")

        # Strategy C: final fallback — use annotated uuids from time entries
        if total_video_duration_seconds == 0 and annotated_uuids_in_range:
            print(f"  Using time-entry uuids ({len(annotated_uuids_in_range)}) as last resort...")
            videos_counted = set()
            for uid in annotated_uuids_in_range:
                if uid in videos_counted:
                    continue
                videos_counted.add(uid)
                lr = lr_by_uuid.get(uid)
                if lr:
                    total_video_duration_seconds += get_duration_seconds(lr)
            print(f"  ✓ Video duration (fallback): {total_video_duration_seconds:.1f}s "
                  f"across {len(videos_counted)} videos")

        print(f"  ✓ Final video duration: {total_video_duration_seconds:.1f}s across {len(videos_counted)} unique videos")

        # ── Weekly Breakdown (for TPT & Ratio charts) ────────────────────
        week_ann_time: dict  = defaultdict(float)
        week_submitted: dict = defaultdict(set)
        week_vid_secs: dict  = defaultdict(float)
        week_vid_seen: dict  = defaultdict(set)

        for entry in time_entries:
            wf_stage   = getattr(entry, "workflow_stage", None)
            stage_type = str(getattr(wf_stage, "stage_type", "")).upper() if wf_stage else ""
            if "ANNOTATION" not in stage_type:
                continue
            seconds      = getattr(entry, "time_spent_seconds", 0) or 0
            period_start = getattr(entry, "period_start_time", None)
            if period_start is None:
                continue
            try:
                if isinstance(period_start, str):
                    period_start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
                iso_year, iso_week, _ = period_start.isocalendar()
                wk = f"{iso_year}-W{iso_week:02d}"
            except Exception:
                continue
            week_ann_time[wk] += seconds

        for log in label_logs_raw:
            if log.action != Action.SUBMIT_TASK:
                continue
            dh = log.data_hash
            try:
                ts = getattr(log, "created_at", None) or getattr(log, "timestamp", None)
                if ts is None:
                    continue
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                iso_year, iso_week, _ = ts.isocalendar()
                wk = f"{iso_year}-W{iso_week:02d}"
            except Exception:
                continue
            week_submitted[wk].add(dh)

        all_weeks = sorted(set(week_ann_time) | set(week_submitted))
        for wk in all_weeks:
            for dh in week_submitted.get(wk, set()):
                if dh in week_vid_seen[wk]:
                    continue
                week_vid_seen[wk].add(dh)
                lr = lr_by_hash.get(dh)
                if lr:
                    week_vid_secs[wk] += get_duration_seconds(lr)

        weekly_data = []
        for wk in all_weeks:
            ann_secs  = week_ann_time.get(wk, 0)
            sub_count = len(week_submitted.get(wk, set()))
            vid_secs  = week_vid_secs.get(wk, 0)
            tpt       = ann_secs / sub_count if sub_count > 0 else 0
            ratio_wk  = ann_secs / vid_secs  if vid_secs  > 0 else None
            try:
                yr, wn = int(wk.split("-W")[0]), int(wk.split("-W")[1])
                week_start = datetime.fromisocalendar(yr, wn, 1)
                label = week_start.strftime("W%V (%b %-d)")
            except Exception:
                label = wk
            weekly_data.append({
                "week":        wk,
                "label":       label,
                "ann_seconds": round(ann_secs),
                "submitted":   sub_count,
                "vid_seconds": round(vid_secs, 1),
                "tpt_seconds": round(tpt),
                "tpt_minutes": round(tpt / 60, 2),
                "ratio":       round(ratio_wk, 3) if ratio_wk is not None else None,
            })

        print(f"  ✓ Weekly breakdown: {len(weekly_data)} weeks")


        def classify(dh):
            if dh in dh_rejected:  return "rejected"
            if dh in dh_approved:  return "approved"
            return "pending"

        ann_rej_stats = {}
        for email, submitted in ann_submits.items():
            n_rej = sum(1 for dh in submitted if classify(dh) == "rejected")
            n_app = sum(1 for dh in submitted if classify(dh) == "approved")
            reviewed = n_app + n_rej
            ann_rej_stats[email] = {
                "submitted": len(submitted),
                "approved":  n_app,
                "rejected":  n_rej,
                "rate": round((n_rej / reviewed * 100), 2) if reviewed > 0 else 0.0,
            }

        rev_rej_stats = {}
        for email in set(rev_approves) | set(rev_rejects):
            all_dh = rev_approves.get(email, set()) | rev_rejects.get(email, set())
            n_rej = sum(1 for dh in all_dh if dh in rev_rejects.get(email, set()))
            n_app = len(all_dh) - n_rej
            total = n_app + n_rej
            rev_rej_stats[email] = {
                "approved": n_app,
                "rejected": n_rej,
                "rate": round((n_rej / total * 100), 2) if total > 0 else 0.0,
            }

        # ── Build Annotators List ───────────────────────────────────────
        annotators_list = []
        for email, ad in ann_data.items():
            tasks_worked = len(ad["data_uuids"])
            total_time   = ad["time_seconds"]
            if tasks_worked == 0 and total_time == 0:
                continue

            avg_tpt = total_time / tasks_worked if tasks_worked > 0 else 0

            dates = ad.get("dates", [])
            if len(dates) >= 2:
                try:
                    date_objs  = [d if isinstance(d, datetime) else datetime.fromisoformat(str(d)) for d in dates]
                    days_active = max(1, (max(date_objs) - min(date_objs)).days + 1)
                except Exception:
                    days_active = 1
            else:
                days_active = 1

            throughput = tasks_worked / days_active if days_active > 0 else 0
            name = format_name_from_email(email)
            ar   = ann_rej_stats.get(email, {})

            annotators_list.append({
                "email":                  email,
                "name":                   name,
                "id":                     get_initials(email),
                "tasks":                  tasks_worked,
                "tasks_submitted":        ar.get("submitted", 0),
                "tasks_rejected":         ar.get("rejected", 0),
                "rejection":              ar.get("rate", 0.0),
                "days":                   days_active,
                "annotation_time_seconds": round(total_time),
                "annotation_time_raw":    format_seconds(total_time),
                "avg_tpt_seconds":        round(avg_tpt),
                "avg_tpt_raw":            format_seconds(avg_tpt),
                "tput":                   round(throughput, 1),
                "flags":                  [],
                "status":                 "good",
            })

        # ── Build Reviewers List ────────────────────────────────────────
        reviewers_list = []
        for email, rd in rev_data.items():
            tasks_reviewed = len(rd["data_uuids"])
            total_time     = rd["time_seconds"]
            if tasks_reviewed == 0 and total_time == 0:
                continue
            avg_tpt = total_time / tasks_reviewed if tasks_reviewed > 0 else 0
            name = format_name_from_email(email)
            rr   = rev_rej_stats.get(email, {})

            reviewers_list.append({
                "email":             email,
                "name":              name,
                "id":                get_initials(email),
                "tasks_reviewed":    tasks_reviewed,
                "rev_approved":      rr.get("approved", 0),
                "rev_rejected":      rr.get("rejected", 0),
                "rev_rejection_rate": rr.get("rate", 0.0),
                "review_time_seconds": round(total_time),
                "review_time_raw":   format_seconds(total_time),
                "avg_tpt_raw":       format_seconds(avg_tpt),
                "total_time_raw":    format_seconds(total_time),
                "flags":             [],
                "status":            "good",
            })

        # ── Outlier Flags ───────────────────────────────────────────────
        if annotators_list:
            tpt_vals = [a["avg_tpt_seconds"] for a in annotators_list if a["avg_tpt_seconds"] > 0]
            tp_vals  = [a["tput"] for a in annotators_list if a["tput"] > 0]
            rr_vals  = [a["rejection"] for a in annotators_list]
            med_tpt  = statistics.median(tpt_vals) if tpt_vals else 0
            med_tp   = statistics.median(tp_vals)  if tp_vals  else 0
            avg_rej  = statistics.mean(rr_vals)    if rr_vals  else 0

            for a in annotators_list:
                flags = []
                if a["rejection"] > avg_rej + 10:
                    flags.append({"label": "high rejection", "type": "red"})
                if med_tpt > 0 and 0 < a["avg_tpt_seconds"] < med_tpt * 0.2:
                    flags.append({"label": "too fast", "type": "amber"})
                if med_tpt > 0 and a["avg_tpt_seconds"] > med_tpt * 1.5:
                    flags.append({"label": "too slow", "type": "amber"})
                if med_tp > 0 and 0 < a["tput"] < med_tp * 0.8:
                    flags.append({"label": "low throughput", "type": "amber"})
                a["flags"] = flags
                if any(f["type"] == "red"   for f in flags): a["status"] = "crit"
                elif any(f["type"] == "amber" for f in flags): a["status"] = "warn"

        status_order = {"crit": 0, "warn": 1, "good": 2}
        annotators_list.sort(key=lambda x: (status_order.get(x["status"], 3), -x["tasks"]))
        reviewers_list.sort(key=lambda x: -x["tasks_reviewed"])

        # ── Aggregates ──────────────────────────────────────────────────
        total_ann_time      = sum(ad["time_seconds"] for ad in ann_data.values())
        total_rev_time      = sum(rd["time_seconds"] for rd in rev_data.values())
        num_annotators      = len(annotators_list)
        num_reviewers       = len(reviewers_list)
        total_tasks_ann       = sum(a["tasks"]          for a in annotators_list)
        total_tasks_rev       = sum(r["tasks_reviewed"] for r in reviewers_list)
        # time_entries ARE properly date-filtered by Encord API.
        # label_logs SUBMIT_TASK is NOT — Encord returns historical submits
        # regardless of the after/before window, so 14d == 90d == All Time.
        # Use unique data_uuids from annotation time entries as the count.
        all_ann_uuids_in_range: set = set()
        for ad in ann_data.values():
            all_ann_uuids_in_range |= ad["data_uuids"]
        total_tasks_submitted = len(all_ann_uuids_in_range) if all_ann_uuids_in_range else total_tasks_ann
        avg_tpt_seconds = (
            total_ann_time / total_tasks_submitted
            if total_tasks_submitted > 0
            else (total_ann_time / total_tasks_ann if total_tasks_ann > 0 else 0)
        )
        print(f"  ── Avg TPT: {total_ann_time:.0f}s / {total_tasks_submitted} tasks (time_entry uuids) = {avg_tpt_seconds:.1f}s = {format_seconds(avg_tpt_seconds)}")

        ratio = (total_ann_time / total_video_duration_seconds
                 if total_video_duration_seconds > 0 else None)
        ratio_display = f"{ratio:.2f}x" if ratio is not None else "—"

        # ── Build Response ──────────────────────────────────────────────
        response = {
            "last_updated":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_filter":   date_label,
            "project_hash":  ph,
            "project_title": project.title,

            "metrics": {
                # Annotation
                "num_annotators":               num_annotators,
                "num_tasks_annotated":          total_tasks_ann,        # unique tasks worked (from time entries)
                "num_tasks_submitted":          total_tasks_submitted,  # unique tasks submitted (= Encord's denominator)
                "total_annotation_time_seconds": round(total_ann_time),
                "total_annotation_time_raw":    format_seconds(total_ann_time),
                "total_annotation_time_hours":  round(total_ann_time / 3600, 2),
                # Video duration
                "video_duration_seconds":  round(total_video_duration_seconds, 1),
                "video_duration_raw":      format_seconds(total_video_duration_seconds),
                "video_duration_hours":    round(total_video_duration_seconds / 3600, 2),
                "videos_counted":          len(videos_counted),
                # TPT — uses submitted task count as denominator (matches Encord Analytics)
                "time_per_task_seconds":   round(avg_tpt_seconds),
                "time_per_task_raw":       format_seconds(avg_tpt_seconds),
                "tpt_denominator":         total_tasks_submitted,
                # Review
                "num_reviewers":           num_reviewers,
                "num_tasks_reviewed":      total_tasks_rev,
                "hours_reviewed_seconds":  round(total_rev_time),
                "hours_reviewed_raw":      format_seconds(total_rev_time),
                "hours_reviewed_hours":    round(total_rev_time / 3600, 2),
                # Ratio
                "ratio":         ratio,
                "ratio_display": ratio_display,
            },

            "annotators":  annotators_list,
            "reviewers":   reviewers_list,
            "weekly_data": weekly_data,
        }

        _set_cache(ck, response)
        print(f"  ✓ 1x response built in {time.time()-t0:.1f}s")
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Data processing error: {str(e)}"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
