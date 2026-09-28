"""Run the same load against MySQL 8 and compare every view with SQLite.

Skipped unless SERVICEOPS_MYSQL_URL is set (CI provides a mysql:8.0 service).
"""
import os

import pytest

from serviceops.db import Database, load

URL = os.environ.get("SERVICEOPS_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SERVICEOPS_MYSQL_URL not set")

VIEWS = {
    "vw_kpi_summary": None, "vw_category_pareto": "category", "vw_priority_sla": "priority",
    "vw_monthly_kpis": "opened_month", "vw_backlog_aging": "age_band",
    "vw_group_workload": "assignment_group", "vw_dq_summary": "dimension, action_taken",
}


@pytest.fixture(scope="module")
def mysql(gated):
    db = Database(URL)
    load(db, gated)
    yield db
    db.close()


@pytest.mark.parametrize("view,order", VIEWS.items())
def test_views_match_sqlite(mysql, db, view, order):
    sql = f"SELECT * FROM {view}" + (f" ORDER BY {order}" if order else "")
    left, right = mysql.query(sql), db.query(sql)
    assert len(left) == len(right)
    for a, b in zip(left, right, strict=True):
        for key in b:
            if isinstance(b[key], float):
                assert a[key] == pytest.approx(b[key], abs=0.011), (view, key)
            else:
                assert a[key] == b[key], (view, key)


def test_daily_backlog_matches(mysql, db):
    sql = "SELECT flow_date, backlog FROM vw_daily_backlog ORDER BY flow_date"
    assert [(r["flow_date"], r["backlog"]) for r in mysql.query(sql)] == \
        [(r["flow_date"], r["backlog"]) for r in db.query(sql)]


def test_analyst_queries_run_on_mysql(mysql):
    from serviceops.db import read_sql, split_statements

    for sql in split_statements(read_sql("reporting_queries.sql")):
        assert mysql.query(sql), sql[:60]
