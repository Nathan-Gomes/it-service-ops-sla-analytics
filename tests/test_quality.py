import pandas as pd
import pytest

from serviceops.quality import run_quality_gate
from serviceops.simulate import N_TICKETS
from serviceops.taxonomy import CATEGORY_BY_NAME, PRIORITY_BY_NAME

# check id -> answer-key field it must catch exactly
EXACT = {
    "U1": "exact_duplicates", "U2": "stale_versions", "C1": "category_variants",
    "C2": "priority_variants", "M1": "missing_category", "M2": "missing_group",
    "M3": "missing_priority", "M4": "missing_opened", "V1": "opened_after_snapshot",
    "V2": "resolved_before_opened", "V3": "response_before_opened",
    "V4": "closed_before_resolved", "V5": "resolved_status_without_time",
    "V6": "open_status_with_resolution",
}
QUARANTINE_FIELDS = ["missing_priority", "missing_opened", "opened_after_snapshot",
                     "resolved_before_opened", "response_before_opened",
                     "closed_before_resolved", "resolved_status_without_time",
                     "open_status_with_resolution"]


@pytest.mark.parametrize("check_id,field", EXACT.items())
def test_each_check_finds_exactly_the_injected_defects(gated, raw_and_key, check_id, field):
    _, key = raw_and_key
    check = next(c for c in gated.checks if c.id == check_id)
    assert check.rows == len(key.as_dict()[field])


def test_quarantine_holds_exactly_the_unfixable_tickets(gated, raw_and_key):
    _, key = raw_and_key
    expected = {i for f in QUARANTINE_FIELDS for i in key.as_dict()[f]}
    assert set(gated.quarantine["ticket_id"]) == expected


def test_row_accounting(gated):
    r = gated.report()
    assert r["rows_in"] == r["rows_clean"] + r["rows_quarantined"] + r["rows_removed"]
    assert r["rows_clean"] + r["rows_quarantined"] == N_TICKETS


def test_repairs_restore_the_original_values(gated, clean_history, raw_and_key):
    _, key = raw_and_key
    truth = clean_history.set_index("ticket_id")
    clean = gated.clean.set_index("ticket_id")
    for field, column in [("category_variants", "category"), ("missing_category", "category"),
                          ("priority_variants", "priority"), ("missing_group", "assignment_group")]:
        ids = key.as_dict()[field]
        assert (clean.loc[ids, column] == truth.loc[ids, column]).all(), field


def test_clean_output_passes_every_rule(gated):
    df = gated.clean
    assert df["ticket_id"].is_unique
    assert set(df["category"]) <= set(CATEGORY_BY_NAME)
    assert set(df["priority"]) <= set(PRIORITY_BY_NAME)
    assert df["opened_at"].notna().all()
    res = df["resolved_at"].notna()
    assert (df.loc[res, "resolved_at"] >= df.loc[res, "opened_at"]).all()


def test_gate_is_idempotent(gated):
    """Re-running the gate on its own output finds nothing to fix."""
    again = gated.clean.drop(columns="dq_repaired").copy()
    for c in ["opened_at", "first_response_at", "resolved_at", "closed_at", "updated_at"]:
        again[c] = again[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    second = run_quality_gate(again.astype(str).replace({"NaT": "", "nan": ""}))
    assert all(c.rows == 0 for c in second.checks)
    assert len(second.clean) == len(gated.clean)


def test_whitespace_and_case_drift_is_caught():
    raw = pd.DataFrame([{
        "ticket_id": "INC1", "opened_at": "2025-01-01 09:00:00", "first_response_at": "",
        "resolved_at": "2025-01-01 10:00:00", "closed_at": "", "updated_at": "2025-01-01 10:00:00",
        "status": "Resolved", "priority": " HIGH ", "category": " Network & VPN",
        "subcategory": "Slow connection", "assignment_group": "Network Operations",
        "assigned_agent": "G. Novak", "channel": "Portal", "department": "Sales",
        "site": "Toronto", "reassignment_count": "0", "reopened": "0", "wait_reason": "",
    }])
    out = run_quality_gate(raw)
    assert out.clean.loc[0, "category"] == "Network & VPN"
    assert out.clean.loc[0, "priority"] == "High"
    assert out.clean.loc[0, "dq_repaired"] == "category relabelled; priority relabelled"
