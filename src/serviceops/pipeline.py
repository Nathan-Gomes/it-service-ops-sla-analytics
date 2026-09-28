"""End-to-end build: simulate -> raw export -> quality gate -> database -> reports."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .analysis import findings
from .db import Database, load, ticket_frame
from .excel import build_workbook
from .quality import run_quality_gate
from .simulate import N_TICKETS, SEED, export_raw, simulate
from .taxonomy import CATEGORIES, PRIORITIES

DEFAULT_OUT = Path(os.environ.get("SERVICEOPS_OUTPUT", "output"))


@dataclass
class BuildResult:
    db_url: str
    out_dir: Path
    quality: dict
    findings: dict
    seconds: float


def export_powerbi(clean: pd.DataFrame, quality: dict, out: Path) -> None:
    """Star schema for Power BI: one fact table and conformed dimensions (see powerbi/)."""
    out.mkdir(parents=True, exist_ok=True)
    fact = ticket_frame(clean)
    fact.to_csv(out / "fact_ticket.csv", index=False)
    dates = pd.date_range(fact["opened_date"].min(), fact["opened_date"].max(), freq="D")
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "year": dates.year, "month": dates.strftime("%Y-%m"),
        "month_name": dates.strftime("%b %Y"), "quarter": "Q" + dates.quarter.astype(str),
        "weekday": dates.strftime("%a"), "is_weekend": (dates.dayofweek >= 5).astype(int),
    }).to_csv(out / "dim_date.csv", index=False)
    pd.DataFrame([{"priority": p.name, "priority_code": p.code, "sort_order": i + 1,
                   "response_target_hours": p.response_target_hours,
                   "resolution_target_hours": p.resolution_target_hours}
                  for i, p in enumerate(PRIORITIES)]).to_csv(out / "dim_priority.csv",
                                                             index=False)
    pd.DataFrame([{"category": c.name, "resolver_group": c.group}
                  for c in CATEGORIES]).to_csv(out / "dim_category.csv", index=False)
    pd.DataFrame(quality["checks"]).drop(columns="examples").to_csv(out / "dq_checks.csv",
                                                                    index=False)


def build(db_url: str | None = None, out_dir: Path = DEFAULT_OUT, n: int = N_TICKETS,
          seed: int = SEED, reports: bool = True) -> BuildResult:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_url = db_url or f"sqlite:///{out_dir / 'serviceops.db'}"
    if db_url.startswith("sqlite:///"):
        Path(db_url.split("sqlite:///", 1)[1]).unlink(missing_ok=True)

    raw, _ = export_raw(simulate(n, seed), seed)
    raw.to_csv(out_dir / "tickets_raw_export.csv", index=False)
    result = run_quality_gate(raw)
    report = result.report()
    result.quarantine.to_csv(out_dir / "quarantine.csv", index=False)

    db = Database(db_url)
    try:
        load(db, result)
        fnd = findings(db)
        (out_dir / "quality_report.json").write_text(json.dumps(report, indent=2))
        (out_dir / "findings.json").write_text(json.dumps(fnd, indent=2))
        if reports:
            build_workbook(db, out_dir / "service_ops_sla_report.xlsx", report)
            export_powerbi(result.clean, report, out_dir / "powerbi")
    finally:
        db.close()
    return BuildResult(db_url, out_dir, report, fnd, round(time.time() - started, 1))
