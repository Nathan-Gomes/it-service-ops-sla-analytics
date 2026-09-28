"""The SQL views, the filtered app queries and an independent pandas calculation must agree."""
import pandas as pd
import pytest

from serviceops import queries as q
from serviceops.taxonomy import PRIORITY_BY_NAME, SNAPSHOT


@pytest.fixture(scope="module")
def frame(gated):
    """SLA outcome recomputed in pandas straight from the gated tickets."""
    df = gated.clean.copy()
    snap = pd.Timestamp(SNAPSHOT)
    target = df["priority"].map(lambda p: PRIORITY_BY_NAME[p].resolution_target_hours)
    elapsed = ((df["resolved_at"].fillna(snap) - df["opened_at"]).dt.total_seconds() / 3600)
    df["breached"] = elapsed.round(2) > target
    df["scored"] = df["resolved_at"].notna() | df["breached"]
    return df


def test_kpi_view_matches_pandas(db, frame):
    view = db.query("SELECT * FROM vw_kpi_summary")[0]
    assert view["total_tickets"] == len(frame)
    assert view["sla_breaches"] == frame["breached"].sum()
    assert view["open_backlog"] == frame["resolved_at"].isna().sum()
    expected = 100 * (1 - frame["breached"].sum() / frame["scored"].sum())
    assert view["sla_compliance_pct"] == pytest.approx(expected, abs=0.01)


def test_view_and_filtered_query_agree_unfiltered(db):
    view = db.query("SELECT * FROM vw_kpi_summary")[0]
    app = q.kpis(db, q.Filters())
    for key, value in view.items():
        assert app[key] == pytest.approx(value), key


def test_pareto_view_matches_query_and_pandas(db, frame):
    view = db.query("SELECT * FROM vw_category_pareto ORDER BY breach_rank")
    app = q.pareto(db, q.Filters())
    counts = frame[frame["breached"]].groupby("category").size().sort_values(ascending=False)
    assert [r["category"] for r in view] == [r["label"] for r in app] == list(counts.index)
    for v, a in zip(view, app, strict=True):
        assert v["breaches"] == a["breaches"]
        assert v["cumulative_share_pct"] == pytest.approx(a["cumulative_share_pct"], abs=0.01)
    assert view[-1]["cumulative_share_pct"] == pytest.approx(100)


def test_backlog_ends_at_the_open_count(db):
    last = db.query("SELECT * FROM vw_daily_backlog ORDER BY flow_date DESC LIMIT 1")[0]
    open_now = db.query("SELECT COUNT(*) AS n FROM tickets WHERE is_resolved = 0")[0]["n"]
    assert last["flow_date"] == SNAPSHOT[:10]
    assert last["backlog"] == open_now
    assert min(r["backlog"] for r in db.query("SELECT backlog FROM vw_daily_backlog")) >= 0


def test_monthly_and_priority_views_add_up(db):
    total = db.query("SELECT COUNT(*) AS n FROM tickets")[0]["n"]
    assert sum(r["tickets_opened"] for r in db.query("SELECT * FROM vw_monthly_kpis")) == total
    assert sum(r["tickets"] for r in db.query("SELECT * FROM vw_priority_sla")) == total
    aging = db.query("SELECT SUM(open_tickets) AS n FROM vw_backlog_aging")[0]["n"]
    assert aging == db.query("SELECT SUM(1 - is_resolved) AS n FROM tickets")[0]["n"]


def test_filters_narrow_every_measure(db):
    everything = q.kpis(db, q.Filters())
    printing = q.kpis(db, q.Filters(dims={"category": ["Printing"]}))
    year = q.kpis(db, q.Filters(start="2025-01-01", end="2025-12-31"))
    assert 0 < printing["total_tickets"] < everything["total_tickets"]
    assert 0 < year["total_tickets"] < everything["total_tickets"]
    both = q.kpis(db, q.Filters(start="2025-01-01", end="2025-12-31",
                                dims={"category": ["Printing"]}))
    assert both["total_tickets"] < min(printing["total_tickets"], year["total_tickets"])


def test_filter_values_are_parameters_not_sql(db):
    hostile = q.Filters(dims={"category": ["x') OR 1=1 --"]})
    assert q.kpis(db, hostile)["total_tickets"] == 0
    assert q.tickets(db, q.Filters(), sort="opened_at; DROP TABLE tickets")["total"] > 0
    assert db.query("SELECT COUNT(*) AS n FROM tickets")[0]["n"] > 0


def test_what_if_is_consistent(db):
    wi = q.what_if(db, q.Filters(), ["Access & Identity", "Network & VPN"])
    kpi = q.kpis(db, q.Filters())
    assert wi["current_compliance_pct"] == pytest.approx(kpi["sla_compliance_pct"], abs=0.01)
    assert wi["what_if_compliance_pct"] > wi["current_compliance_pct"]
    assert wi["focus_breach_rate_pct"] > wi["rest_breach_rate_pct"]


def test_analyst_queries_run(db):
    from serviceops.db import read_sql, split_statements

    statements = split_statements(read_sql("reporting_queries.sql"))
    assert len(statements) == 7
    for sql in statements:
        assert db.query(sql), sql[:60]
