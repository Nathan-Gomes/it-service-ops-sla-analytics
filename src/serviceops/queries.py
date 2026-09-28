"""Filtered analytical queries over ticket_sla, the materialized output of vw_ticket_sla.

The views in sql/views.sql answer the unfiltered questions for Excel and Power BI. The
dashboard needs the same measures under any filter, so these queries apply the same SLA
expressions with a parameterised WHERE clause. tests/test_sql.py holds both paths to the same
numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .db import Database

SLA = "ticket_sla"  # materialized vw_ticket_sla (see db.materialize)
COMPLIANCE = "ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)"
RESPONSE = "ROUND(100.0 * SUM(response_met) / NULLIF(SUM(response_scored), 0), 2)"
BREACH_RATE = "ROUND(100.0 * SUM(breached) / NULLIF(SUM(sla_scored), 0), 2)"
AVG_RES = "ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2)"

FILTER_COLUMNS = {"category": "category", "priority": "priority", "group": "assignment_group",
                  "site": "site", "channel": "channel", "department": "department"}
SLA_STATES = ["Met", "Breached", "Open - breached", "Open - within SLA"]


@dataclass
class Filters:
    start: str | None = None  # opened_date >= start
    end: str | None = None  # opened_date <= end
    dims: dict[str, list[str]] = field(default_factory=dict)

    def where(self, *, dates: bool = True, extra: list[str] | None = None,
              params: list | None = None) -> tuple[str, list]:
        clauses, args = list(extra or []), list(params or [])
        if dates and self.start:
            clauses.append("opened_date >= ?")
            args.append(self.start)
        if dates and self.end:
            clauses.append("opened_date <= ?")
            args.append(self.end)
        for key, values in self.dims.items():
            if values:
                clauses.append(f"{FILTER_COLUMNS[key]} IN ({', '.join('?' * len(values))})")
                args.extend(values)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def percentile(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 2) if values else None


def kpis(db: Database, f: Filters) -> dict:
    w, a = f.where()
    row = db.query(f"""
        SELECT COUNT(*) AS total_tickets,
               COALESCE(SUM(1 - is_resolved), 0) AS open_backlog,
               COALESCE(SUM(CASE WHEN is_resolved = 0 AND breached = 1 THEN 1 ELSE 0 END), 0)
                   AS open_breached,
               COALESCE(SUM(breached), 0) AS sla_breaches,
               {COMPLIANCE} AS sla_compliance_pct,
               {RESPONSE} AS response_compliance_pct,
               {AVG_RES} AS avg_resolution_hours,
               ROUND(100.0 * SUM(CASE WHEN reassignment_count > 0 THEN 1 ELSE 0 END)
                     / NULLIF(COUNT(*), 0), 2) AS reassigned_pct,
               ROUND(100.0 * SUM(reopened) / NULLIF(COUNT(*), 0), 2) AS reopened_pct
        FROM {SLA}{w}""", a)[0]
    w2, a2 = f.where(extra=["is_resolved = 1"])
    hours = [r["elapsed_hours"] for r in db.query(
        f"SELECT elapsed_hours FROM {SLA}{w2}", a2)]
    row["median_resolution_hours"] = percentile(hours, 50)
    row["p90_resolution_hours"] = percentile(hours, 90)
    return row


def monthly(db: Database, f: Filters) -> list[dict]:
    w, a = f.where()
    return db.query(f"""
        SELECT opened_month, COUNT(*) AS tickets_opened, SUM(breached) AS sla_breaches,
               {COMPLIANCE} AS sla_compliance_pct, {AVG_RES} AS avg_resolution_hours,
               {RESPONSE} AS response_compliance_pct
        FROM {SLA}{w} GROUP BY opened_month ORDER BY opened_month""", a)


def backlog(db: Database, f: Filters) -> list[dict]:
    """Daily opened/resolved flow and the running open backlog.

    Dimension filters apply to the flow; the date filter only trims the output, because the
    backlog on a given day depends on everything opened before it.
    """
    w, a = f.where(dates=False)
    w_res, a_res = f.where(dates=False, extra=["resolved_date IS NOT NULL"])
    rows = db.query(f"""
        WITH flow AS (
            SELECT opened_date AS flow_date, COUNT(*) AS opened, 0 AS resolved
            FROM {SLA}{w} GROUP BY opened_date
            UNION ALL
            SELECT resolved_date, 0, COUNT(*) FROM {SLA}{w_res} GROUP BY resolved_date
        ), daily AS (
            SELECT flow_date, SUM(opened) AS opened, SUM(resolved) AS resolved
            FROM flow GROUP BY flow_date
        )
        SELECT flow_date, opened, resolved,
               SUM(opened - resolved) OVER (ORDER BY flow_date ROWS BETWEEN UNBOUNDED PRECEDING
                                            AND CURRENT ROW) AS backlog
        FROM daily ORDER BY flow_date""", a + a_res)
    return [r for r in rows if (not f.start or r["flow_date"] >= f.start)
            and (not f.end or r["flow_date"] <= f.end)]


def aging(db: Database, f: Filters) -> list[dict]:
    w, a = f.where(extra=["is_resolved = 0"])
    band = """CASE WHEN elapsed_hours < 24 THEN 'Under 1 day'
                   WHEN elapsed_hours < 72 THEN '1-3 days'
                   WHEN elapsed_hours < 168 THEN '3-7 days'
                   WHEN elapsed_hours < 720 THEN '7-30 days'
                   ELSE 'Over 30 days' END"""
    rows = {r["age_band"]: r for r in db.query(
        f"SELECT {band} AS age_band, COUNT(*) AS open_tickets, SUM(breached) AS already_breached"
        f" FROM {SLA}{w} GROUP BY {band}", a)}
    order = ["Under 1 day", "1-3 days", "3-7 days", "7-30 days", "Over 30 days"]
    return [rows.get(b, {"age_band": b, "open_tickets": 0, "already_breached": 0})
            for b in order]


def by_priority(db: Database, f: Filters) -> list[dict]:
    w, a = f.where()
    return db.query(f"""
        SELECT priority, priority_code, priority_order, resolution_target_hours,
               response_target_hours, COUNT(*) AS tickets, SUM(breached) AS breaches,
               {COMPLIANCE} AS sla_compliance_pct, {RESPONSE} AS response_compliance_pct,
               {AVG_RES} AS avg_resolution_hours
        FROM {SLA}{w}
        GROUP BY priority, priority_code, priority_order, resolution_target_hours,
                 response_target_hours
        ORDER BY priority_order""", a)


def pareto(db: Database, f: Filters, column: str = "category") -> list[dict]:
    w, a = f.where()
    rows = db.query(f"""
        SELECT {column} AS label, COUNT(*) AS tickets, SUM(breached) AS breaches,
               {BREACH_RATE} AS breach_rate_pct, {AVG_RES} AS avg_resolution_hours
        FROM {SLA}{w} GROUP BY {column}
        ORDER BY SUM(breached) DESC, {column}""", a)
    total_t = sum(r["tickets"] for r in rows) or 1
    total_b = sum(r["breaches"] or 0 for r in rows) or 1
    running = 0
    for rank, r in enumerate(rows, 1):
        r["breaches"] = r["breaches"] or 0
        running += r["breaches"]
        r["share_of_volume_pct"] = round(100 * r["tickets"] / total_t, 2)
        r["share_of_breaches_pct"] = round(100 * r["breaches"] / total_b, 2)
        r["cumulative_share_pct"] = round(100 * running / total_b, 2)
        r["breach_rank"] = rank
    return rows


def matrix(db: Database, f: Filters) -> list[dict]:
    w, a = f.where()
    return db.query(f"""
        SELECT category, priority, priority_order, COUNT(*) AS tickets,
               SUM(breached) AS breaches, {BREACH_RATE} AS breach_rate_pct
        FROM {SLA}{w} GROUP BY category, priority, priority_order""", a)


def drivers(db: Database, f: Filters, categories: list[str]) -> list[dict]:
    """Breach rate by third-party wait and hand-off count, inside the given categories."""
    marks = ", ".join("?" * len(categories))
    w, a = f.where(extra=[f"category IN ({marks})"], params=categories)
    return db.query(f"""
        SELECT category, waited_on_third_party, hop_bucket, COUNT(*) AS tickets,
               SUM(breached) AS breaches, {BREACH_RATE} AS breach_rate_pct
        FROM {SLA}{w}
        GROUP BY category, waited_on_third_party, hop_bucket
        ORDER BY category, waited_on_third_party, hop_bucket""", a)


def subcategories(db: Database, f: Filters, categories: list[str]) -> list[dict]:
    marks = ", ".join("?" * len(categories))
    w, a = f.where(extra=[f"category IN ({marks})"], params=categories)
    return db.query(f"""
        SELECT category, subcategory, COUNT(*) AS tickets, SUM(breached) AS breaches,
               {BREACH_RATE} AS breach_rate_pct, {AVG_RES} AS avg_resolution_hours
        FROM {SLA}{w} GROUP BY category, subcategory
        ORDER BY SUM(breached) DESC""", a)


def groups(db: Database, f: Filters) -> list[dict]:
    w, a = f.where()
    return db.query(f"""
        SELECT assignment_group, COUNT(*) AS tickets, SUM(1 - is_resolved) AS open_tickets,
               SUM(breached) AS breaches, {COMPLIANCE} AS sla_compliance_pct,
               {AVG_RES} AS avg_resolution_hours,
               ROUND(AVG(reassignment_count), 2) AS avg_reassignments
        FROM {SLA}{w} GROUP BY assignment_group ORDER BY COUNT(*) DESC""", a)


def agents(db: Database, f: Filters) -> list[dict]:
    w, a = f.where()
    return db.query(f"""
        SELECT assigned_agent, assignment_group, COUNT(*) AS tickets,
               SUM(1 - is_resolved) AS open_tickets, SUM(breached) AS breaches,
               {COMPLIANCE} AS sla_compliance_pct, {AVG_RES} AS avg_resolution_hours
        FROM {SLA}{w} GROUP BY assigned_agent, assignment_group
        ORDER BY assignment_group, assigned_agent""", a)


SORTABLE = {"ticket_id", "opened_at", "priority_order", "category", "elapsed_hours",
            "assignment_group", "sla_state", "reassignment_count"}
TICKET_FIELDS = ("ticket_id, opened_at, resolved_at, status, priority, category, subcategory, "
                 "assignment_group, assigned_agent, site, channel, reassignment_count, "
                 "wait_reason, elapsed_hours, resolution_target_hours, sla_state, dq_repaired")


def tickets(db: Database, f: Filters, *, state: str | None = None, search: str | None = None,
            sort: str = "opened_at", descending: bool = True, limit: int = 50,
            offset: int = 0) -> dict:
    extra, params = [], []
    if state in SLA_STATES:
        extra.append("sla_state = ?")
        params.append(state)
    if search:
        extra.append("(ticket_id LIKE ? OR subcategory LIKE ? OR assigned_agent LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    w, a = f.where(extra=extra, params=params)
    total = db.query(f"SELECT COUNT(*) AS n FROM {SLA}{w}", a)[0]["n"]
    col = sort if sort in SORTABLE else "opened_at"
    order = f"{col} {'DESC' if descending else 'ASC'}, ticket_id"
    rows = db.query(f"SELECT {TICKET_FIELDS} FROM {SLA}{w} ORDER BY {order} "
                    f"LIMIT {int(limit)} OFFSET {int(offset)}", a)
    return {"total": total, "rows": rows}


def what_if(db: Database, f: Filters, categories: list[str]) -> dict:
    """Compliance if the named categories breached at the rate of the rest of the desk."""
    marks = ", ".join("?" * len(categories))
    w_in, a_in = f.where(extra=[f"category IN ({marks})"], params=categories)
    w_out, a_out = f.where(extra=[f"category NOT IN ({marks})"], params=categories)
    q = ("SELECT COALESCE(SUM(sla_scored), 0) AS scored, COALESCE(SUM(breached), 0) AS breaches "
         f"FROM {SLA}")
    inside = db.query(q + w_in, a_in)[0]
    rest = db.query(q + w_out, a_out)[0]
    scored = inside["scored"] + rest["scored"]
    if not scored or not rest["scored"]:
        return {}
    rest_rate = rest["breaches"] / rest["scored"]
    expected = rest["breaches"] + inside["scored"] * rest_rate
    actual = inside["breaches"] + rest["breaches"]
    return {
        "current_compliance_pct": round(100 * (1 - actual / scored), 2),
        "what_if_compliance_pct": round(100 * (1 - expected / scored), 2),
        "breaches_avoided": round(actual - expected),
        "rest_breach_rate_pct": round(100 * rest_rate, 2),
        "focus_breach_rate_pct": round(100 * inside["breaches"] / inside["scored"], 2)
        if inside["scored"] else None,
    }


AT_RISK_PCT = 75.0  # share of the SLA target at which an open ticket is flagged


def watchlist(db: Database, f: Filters, limit: int = 12) -> dict:
    """Open tickets ranked by how much of their resolution target they have used."""
    w, a = f.where(extra=["is_resolved = 0"])
    used = "ROUND(100.0 * elapsed_hours / resolution_target_hours, 1)"
    rows = db.query(f"""
        SELECT ticket_id, opened_at, priority, category, subcategory, assignment_group,
               assigned_agent, wait_reason, elapsed_hours, resolution_target_hours,
               {used} AS target_used_pct
        FROM {SLA}{w}
        ORDER BY {used} DESC, ticket_id""", a)
    for r in rows:
        pct = r["target_used_pct"]
        r["band"] = "Breached" if pct > 100 else "At risk" if pct >= AT_RISK_PCT else "On track"
    counts = {band: sum(r["band"] == band for r in rows)
              for band in ("Breached", "At risk", "On track")}
    return {"counts": counts, "at_risk_pct": AT_RISK_PCT, "rows": rows[:limit]}
