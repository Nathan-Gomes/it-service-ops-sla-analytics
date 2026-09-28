"""Rebuild and copy the small, reviewable outputs into the repository.

reports/ holds the Excel workbook, quality report and findings; data/ holds a 1,000-row
sample of the raw export so the defects can be inspected without running anything.
"""
import shutil
from pathlib import Path

import pandas as pd

from serviceops.pipeline import build

ROOT = Path(__file__).resolve().parents[1]

result = build(out_dir=ROOT / "output")
reports = ROOT / "reports"
reports.mkdir(exist_ok=True)
for name in ["service_ops_sla_report.xlsx", "quality_report.json", "findings.json"]:
    shutil.copy(result.out_dir / name, reports / name)
(ROOT / "data").mkdir(exist_ok=True)
raw = pd.read_csv(result.out_dir / "tickets_raw_export.csv", dtype=str, keep_default_na=False)
raw.head(1000).to_csv(ROOT / "data" / "sample_raw_export.csv", index=False)
print(f"Published reports/ and data/sample_raw_export.csv ({result.seconds}s build)")
