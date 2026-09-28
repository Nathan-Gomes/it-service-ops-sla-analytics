"""Data-quality gate between the raw ITSM export and every report.

Each check either repairs a record it can fix deterministically or quarantines it with a
reason, so nothing questionable reaches an SLA number silently. The gate returns the clean
tickets, the quarantine, and a report with one entry per check.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from .taxonomy import (
    CATEGORY_ALIASES,
    CATEGORY_BY_NAME,
    PRIORITY_ALIASES,
    PRIORITY_BY_NAME,
    SNAPSHOT,
    SUBCATEGORY_TO_CATEGORY,
)

REQUIRED = ["ticket_id", "opened_at", "status", "priority", "category", "subcategory"]
STATUSES = {"Open", "In Progress", "Pending", "Resolved", "Closed"}
RESOLVED_STATUSES = {"Resolved", "Closed"}
TIMESTAMPS = ["opened_at", "first_response_at", "resolved_at", "closed_at", "updated_at"]


@dataclass
class Check:
    id: str
    dimension: str  # Uniqueness | Completeness | Consistency | Validity
    name: str
    rule: str
    action: str  # removed | repaired | quarantined
    rows: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class QualityResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    checks: list[Check]
    rows_in: int

    @property
    def rows_out(self) -> int:
        return len(self.clean)

    def report(self) -> dict:
        return {
            "rows_in": self.rows_in,
            "rows_clean": self.rows_out,
            "rows_quarantined": len(self.quarantine),
            "rows_removed": self.rows_in - self.rows_out - len(self.quarantine),
            "rows_repaired": int(self.clean["dq_repaired"].ne("").sum()),
            "checks": [asdict(c) for c in self.checks],
        }


def _norm(value: str) -> str:
    return " ".join(str(value).split()).lower()


def run_quality_gate(raw: pd.DataFrame, snapshot: str = SNAPSHOT) -> QualityResult:
    df = raw.copy().fillna("").astype(str)
    # Labels keep their stray whitespace so the consistency checks count it as drift.
    for col in df.columns.difference(["category", "priority"]):
        df[col] = df[col].str.strip()
    rows_in = len(df)
    checks: list[Check] = []
    quarantined: list[pd.DataFrame] = []
    repaired = pd.Series("", index=df.index)

    def note(mask: pd.Series, label: str) -> None:
        idx = mask[mask].index
        repaired.loc[idx] = (repaired.loc[idx] + "; " + label).str.lstrip("; ")

    def quarantine(mask: pd.Series, check: Check) -> None:
        nonlocal df
        check.rows = int(mask.sum())
        check.examples = df.loc[mask, "ticket_id"].head(5).tolist()
        if check.rows:
            q = df.loc[mask].copy()
            q["dq_reason"] = check.name
            quarantined.append(q)
            df = df.loc[~mask]
        checks.append(check)

    # 1. Uniqueness -----------------------------------------------------------------------------
    dup = df.duplicated(keep="first")
    c = Check("U1", "Uniqueness", "Exact duplicate rows",
              "The same row exported more than once", "removed", int(dup.sum()),
              df.loc[dup, "ticket_id"].head(5).tolist())
    df = df.loc[~dup]
    checks.append(c)

    df = df.assign(_upd=pd.to_datetime(df["updated_at"], errors="coerce"))
    df = df.sort_values(["ticket_id", "_upd"], na_position="first")
    stale = df.duplicated("ticket_id", keep="last")
    checks.append(Check("U2", "Uniqueness", "Superseded ticket versions",
                        "Same ticket id exported twice; keep the most recently updated copy",
                        "removed", int(stale.sum()), df.loc[stale, "ticket_id"].head(5).tolist()))
    df = df.loc[~stale].drop(columns="_upd").sort_index()
    repaired = repaired.loc[df.index]

    # 2. Consistency: classification labels ---------------------------------------------------
    canon_cat = df["category"].isin(CATEGORY_BY_NAME)
    mapped = df["category"].map(lambda v: CATEGORY_ALIASES.get(_norm(v)) if v else None)
    fix = ~canon_cat & mapped.notna()
    checks.append(Check("C1", "Consistency", "Non-standard category label",
                        "Legacy or free-text category mapped to the canonical taxonomy",
                        "repaired", int(fix.sum()), df.loc[fix, "category"].head(5).tolist()))
    note(fix, "category relabelled")
    df.loc[fix, "category"] = mapped[fix]

    canon_p = df["priority"].isin(PRIORITY_BY_NAME)
    mapped_p = df["priority"].map(lambda v: PRIORITY_ALIASES.get(_norm(v)) if v else None)
    fix = ~canon_p & mapped_p.notna()
    checks.append(Check("C2", "Consistency", "Non-standard priority label",
                        "P1-P4, numbered and abbreviated priorities mapped to the SLA policy",
                        "repaired", int(fix.sum()), df.loc[fix, "priority"].head(5).tolist()))
    note(fix, "priority relabelled")
    df.loc[fix, "priority"] = mapped_p[fix]

    # 3. Completeness -------------------------------------------------------------------------
    blank_cat = df["category"].eq("")
    inferred = df["subcategory"].map(SUBCATEGORY_TO_CATEGORY)
    fix = blank_cat & inferred.notna()
    checks.append(Check("M1", "Completeness", "Missing category",
                        "Category inferred from the subcategory, which belongs to exactly one "
                        "category", "repaired", int(fix.sum()),
                        df.loc[fix, "ticket_id"].head(5).tolist()))
    note(fix, "category inferred")
    df.loc[fix, "category"] = inferred[fix]

    blank_group = df["assignment_group"].eq("")
    routed = df["category"].map(lambda v: CATEGORY_BY_NAME[v].group if v in CATEGORY_BY_NAME
                                else None)
    fix = blank_group & routed.notna()
    checks.append(Check("M2", "Completeness", "Missing assignment group",
                        "Group restored from the routing rule for the ticket's category",
                        "repaired", int(fix.sum()), df.loc[fix, "ticket_id"].head(5).tolist()))
    note(fix, "group from routing rule")
    df.loc[fix, "assignment_group"] = routed[fix]

    quarantine(df["priority"].eq(""),
               Check("M3", "Completeness", "Missing priority",
                     "No priority means no SLA target, so the ticket cannot be scored",
                     "quarantined"))
    quarantine(df["opened_at"].eq(""),
               Check("M4", "Completeness", "Missing opened time",
                     "Without an opened time the SLA clock has no start", "quarantined"))
    quarantine(~df["category"].isin(CATEGORY_BY_NAME) | ~df["priority"].isin(PRIORITY_BY_NAME)
               | ~df["status"].isin(STATUSES),
               Check("C3", "Consistency", "Unmappable classification",
                     "Category, priority or status outside the taxonomy after repair",
                     "quarantined"))

    # 4. Validity: timelines ------------------------------------------------------------------
    ts = {c: pd.to_datetime(df[c].replace("", None), errors="coerce") for c in TIMESTAMPS}
    snap = pd.Timestamp(snapshot)
    resolved_status = df["status"].isin(RESOLVED_STATUSES)

    rules = [
        ("V1", "Opened after the export", "Opened time later than the snapshot it was exported in",
         ts["opened_at"] > snap),
        ("V2", "Resolved before opened", "Resolved time earlier than opened time",
         ts["resolved_at"] < ts["opened_at"]),
        ("V3", "Responded before opened", "First response earlier than opened time",
         ts["first_response_at"] < ts["opened_at"]),
        ("V4", "Closed before resolved", "Closed time earlier than resolved time",
         ts["closed_at"] < ts["resolved_at"]),
        ("V5", "Resolved status without a resolved time",
         "Status says Resolved or Closed but the resolved time is blank",
         resolved_status & ts["resolved_at"].isna()),
        ("V6", "Open status with a resolved time",
         "Status says the ticket is still active but it carries a resolved time",
         ~resolved_status & ts["resolved_at"].notna()),
    ]
    for cid, name, rule, mask in rules:
        mask = mask.reindex(df.index, fill_value=False)
        quarantine(mask, Check(cid, "Validity", name, rule, "quarantined"))

    clean = df.copy()
    for c in TIMESTAMPS:
        clean[c] = ts[c].loc[clean.index]
    clean["reassignment_count"] = pd.to_numeric(clean["reassignment_count"]).astype(int)
    clean["reopened"] = pd.to_numeric(clean["reopened"]).astype(int)
    clean["dq_repaired"] = repaired.loc[clean.index]
    clean = clean.sort_values("opened_at").reset_index(drop=True)

    quarantine_df = (pd.concat(quarantined, ignore_index=True) if quarantined
                     else pd.DataFrame(columns=[*raw.columns, "dq_reason"]))
    return QualityResult(clean, quarantine_df, checks, rows_in)
