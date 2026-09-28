"""Dashboard API. Every endpoint is a filtered SQL query against the reporting layer."""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import queries as q
from .analysis import findings
from .db import Database
from .pipeline import DEFAULT_OUT, build
from .taxonomy import CATEGORIES, PRIORITIES, SLA_GOAL_PCT, SNAPSHOT

STATIC = Path(__file__).parent / "static"
OUT = Path(os.environ.get("SERVICEOPS_OUTPUT", DEFAULT_OUT))
DB_PATH = OUT / "serviceops.db"

app = FastAPI(title="IT Service Ops & SLA Analytics", version="1.0.0",
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

_lock = threading.Lock()

CSP = "; ".join([
    "default-src 'self'", "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com", "img-src 'self' data:", "connect-src 'self'",
    "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'",
])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@lru_cache(maxsize=1)
def database() -> Database:
    """Open the SQLite build, running the pipeline first if it has not been built."""
    with _lock:
        if not DB_PATH.exists() or not (OUT / "quality_report.json").exists():
            build(out_dir=OUT)
        return Database(f"sqlite:///{DB_PATH}")


def quality_report() -> dict:
    return json.loads((OUT / "quality_report.json").read_text())


def filters(start: str | None, end: str | None, category: list[str] | None,
            priority: list[str] | None, group: list[str] | None, site: list[str] | None,
            channel: list[str] | None) -> q.Filters:
    return q.Filters(start=start or None, end=end or None,
                     dims={"category": category or [], "priority": priority or [],
                           "group": group or [], "site": site or [], "channel": channel or []})


def common(start: str | None = None, end: str | None = None,
           category: list[str] | None = Query(None), priority: list[str] | None = Query(None),
           group: list[str] | None = Query(None), site: list[str] | None = Query(None),
           channel: list[str] | None = Query(None)) -> q.Filters:
    return filters(start, end, category, priority, group, site, channel)


FilterDep = Depends(common)


@app.get("/api/health")
def health() -> dict:
    db = database()
    n = db.query("SELECT COUNT(*) AS n FROM tickets")[0]["n"]
    return {"status": "ok", "version": app.version, "tickets": n,
            "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7] or None}


@app.get("/api/meta")
def meta() -> dict:
    db = database()
    span = db.query("SELECT MIN(opened_date) AS first, MAX(opened_date) AS last FROM tickets")[0]

    def distinct(col: str) -> list[str]:
        return [r["v"] for r in db.query(f"SELECT DISTINCT {col} AS v FROM tickets ORDER BY v")]

    return {
        "snapshot": SNAPSHOT, "sla_goal_pct": SLA_GOAL_PCT,
        "first_date": span["first"], "last_date": span["last"],
        "categories": [c.name for c in CATEGORIES],
        "priorities": [{"name": p.name, "code": p.code,
                        "response_target_hours": p.response_target_hours,
                        "resolution_target_hours": p.resolution_target_hours}
                       for p in PRIORITIES],
        "groups": distinct("assignment_group"), "sites": distinct("site"),
        "channels": distinct("channel"), "sla_states": q.SLA_STATES,
    }


@app.get("/api/overview")
def overview(f: q.Filters = FilterDep) -> dict:
    db = database()
    return {"kpis": q.kpis(db, f), "monthly": q.monthly(db, f), "backlog": q.backlog(db, f),
            "aging": q.aging(db, f), "priority": q.by_priority(db, f), "groups": q.groups(db, f)}


@app.get("/api/breaches")
def breaches(f: q.Filters = FilterDep) -> dict:
    db = database()
    out = findings(db, f)
    top = out.get("top_categories") or []
    out.update({
        "matrix": q.matrix(db, f),
        "drivers": q.drivers(db, f, top) if top else [],
        "subcategories": q.subcategories(db, f, top) if top else [],
    })
    return out


@app.get("/api/agents")
def agents(f: q.Filters = FilterDep) -> list[dict]:
    return q.agents(database(), f)


@app.get("/api/quality")
def quality() -> dict:
    db = database()
    report = quality_report()
    report["quarantine"] = db.query(
        "SELECT ticket_id, dq_reason, raw_record FROM dq_quarantine ORDER BY dq_reason, ticket_id")
    for row in report["quarantine"]:
        row["raw_record"] = json.loads(row["raw_record"])
    report["repaired_breakdown"] = db.query(
        "SELECT dq_repaired AS repair, COUNT(*) AS tickets FROM tickets WHERE dq_repaired <> '' "
        "GROUP BY dq_repaired ORDER BY COUNT(*) DESC")
    return report


@app.get("/api/tickets")
def tickets(f: q.Filters = FilterDep, state: str | None = None, search: str | None = None,
            sort: str = "opened_at", desc: bool = True,
            limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    return q.tickets(database(), f, state=state, search=search, sort=sort, descending=desc,
                     limit=limit, offset=offset)


@app.get("/api/tickets.csv")
def tickets_csv(f: q.Filters = FilterDep, state: str | None = None,
                search: str | None = None) -> StreamingResponse:
    data = q.tickets(database(), f, state=state, search=search, limit=100_000)["rows"]
    buf = io.StringIO()
    if data:
        writer = csv.DictWriter(buf, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="tickets.csv"'})


@app.get("/api/report.xlsx")
def report_xlsx() -> FileResponse:
    database()
    path = OUT / "service_ops_sla_report.xlsx"
    if not path.exists():
        raise HTTPException(404, "Report has not been built")
    return FileResponse(path, filename="service_ops_sla_report.xlsx", media_type=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text())
