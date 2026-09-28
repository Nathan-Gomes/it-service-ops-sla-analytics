"""Command line: `serviceops build` runs the pipeline, `serviceops serve` starts the dashboard."""
from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import DEFAULT_OUT, build


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="serviceops")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="simulate, quality-gate, load and report")
    b.add_argument("--db", help="sqlite:///path.db (default) or mysql://user:pass@host/db")
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    b.add_argument("--tickets", type=int, default=50_000)
    b.add_argument("--no-reports", action="store_true", help="skip Excel and Power BI exports")
    s = sub.add_parser("serve", help="run the dashboard")
    s.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "build":
        r = build(args.db, args.out, n=args.tickets, reports=not args.no_reports)
        q, f = r.quality, r.findings
        print(f"Loaded {q['rows_clean']:,} clean tickets into {r.db_url} in {r.seconds}s")
        print(f"  quality gate: {q['rows_in']:,} rows in, {q['rows_removed']:,} removed, "
              f"{q['rows_repaired']:,} repaired, {q['rows_quarantined']:,} quarantined")
        print(f"  SLA compliance {f['kpis']['sla_compliance_pct']}%, "
              f"{f['kpis']['sla_breaches']:,} breaches")
        print(f"  {f.get('headline', '')}")
        print(f"  outputs in {r.out_dir}/")
    else:
        import uvicorn

        uvicorn.run("serviceops.app:app", host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
