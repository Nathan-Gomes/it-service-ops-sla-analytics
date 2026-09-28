import pandas as pd

from serviceops.simulate import N_TICKETS, simulate
from serviceops.taxonomy import CATEGORY_BY_NAME, PRIORITY_BY_NAME, SNAPSHOT


def test_fifty_thousand_unique_tickets(clean_history):
    assert len(clean_history) == N_TICKETS
    assert clean_history["ticket_id"].is_unique


def test_simulation_is_deterministic(clean_history):
    again = simulate()
    pd.testing.assert_frame_equal(clean_history, again)


def test_clean_history_is_internally_consistent(clean_history):
    df = clean_history
    snap = pd.Timestamp(SNAPSHOT)
    assert (df["opened_at"] <= snap).all()
    resolved = df["resolved_at"].notna()
    assert (df.loc[resolved, "resolved_at"] >= df.loc[resolved, "opened_at"]).all()
    closed = df["closed_at"].notna()
    assert (df.loc[closed, "closed_at"] >= df.loc[closed, "resolved_at"]).all()
    responded = df["first_response_at"].notna()
    assert (df.loc[responded, "first_response_at"] >= df.loc[responded, "opened_at"]).all()
    assert set(df.loc[resolved, "status"]) <= {"Resolved", "Closed"}
    assert set(df.loc[~resolved, "status"]) <= {"Open", "In Progress", "Pending"}
    assert set(df["category"]) == set(CATEGORY_BY_NAME)
    assert set(df["priority"]) == set(PRIORITY_BY_NAME)


def test_groups_follow_routing(clean_history):
    expected = clean_history["category"].map(lambda c: CATEGORY_BY_NAME[c].group)
    assert (clean_history["assignment_group"] == expected).all()


def test_export_adds_duplicates_and_stale_versions(raw_and_key):
    raw, key = raw_and_key
    assert len(raw) == N_TICKETS + len(key.exact_duplicates) + len(key.stale_versions)
    assert all(raw[c].map(lambda v: isinstance(v, str)).all() for c in raw.columns)  # text


def test_each_ticket_carries_at_most_one_defect(raw_and_key):
    _, key = raw_and_key
    ids = [i for group in key.as_dict().values() for i in group]
    assert len(ids) == len(set(ids))
