"""Load quality-gated tickets into SQLite (default) or MySQL 8 and create the reporting views."""
from __future__ import annotations

import json
import re
import sqlite3
from decimal import Decimal
from importlib import resources
from urllib.parse import unquote, urlparse

import pandas as pd

from .quality import QualityResult
from .taxonomy import CATEGORIES, PRIORITIES, SNAPSHOT

TICKET_COLUMNS = [
    "ticket_id", "opened_at", "first_response_at", "resolved_at", "closed_at", "updated_at",
    "status", "priority", "category", "subcategory", "assignment_group", "assigned_agent",
    "channel", "department", "site", "reassignment_count", "reopened", "wait_reason",
    "dq_repaired", "opened_date", "opened_month", "resolved_date", "is_resolved",
    "elapsed_hours", "response_hours",
]


class Database:
    """A thin DB-API wrapper that hides the two parameter styles."""

    def __init__(self, url: str):
        self.url = url
        parsed = urlparse(url)
        self.dialect = parsed.scheme.split("+")[0]
        if self.dialect == "sqlite":
            path = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ":memory:"
            self.conn = sqlite3.connect(path or ":memory:", check_same_thread=False)
            self.param = "?"
        elif self.dialect == "mysql":
            import pymysql  # optional dependency: pip install '.[mysql]'

            self.conn = pymysql.connect(
                host=parsed.hostname or "localhost", port=parsed.port or 3306,
                user=unquote(parsed.username or "root"),
                password=unquote(parsed.password or ""),
                database=parsed.path.lstrip("/") or None, autocommit=False)
            self.param = "%s"
        else:
            raise ValueError(f"Unsupported database url: {url}")

    def execute_script(self, sql: str) -> None:
        cur = self.conn.cursor()
        for statement in split_statements(sql):
            cur.execute(statement)
        self.conn.commit()

    def query(self, sql: str, params: list | tuple = ()) -> list[dict]:
        if self.param != "?":
            sql = sql.replace("?", self.param)
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, (_plain(v) for v in row), strict=True)) for row in cur.fetchall()]

    def insert_many(self, table: str, columns: list[str], rows: list[tuple]) -> None:
        marks = ", ".join([self.param] * len(columns))
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})"
        cur = self.conn.cursor()
        for start in range(0, len(rows), 5000):
            cur.executemany(sql, rows[start:start + 5000])
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _plain(value):
    """MySQL returns Decimal and date objects; make every row JSON-ready like SQLite's."""
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value.as_tuple().exponent >= 0 else float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
    return value


def split_statements(sql: str) -> list[str]:
    body = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in body.split(";") if s.strip()]


def read_sql(name: str) -> str:
    return resources.files("serviceops").joinpath("sql").joinpath(name).read_text()


def ticket_frame(clean: pd.DataFrame, snapshot: str = SNAPSHOT) -> pd.DataFrame:
    """Add the derived columns the schema stores next to each ticket."""
    snap = pd.Timestamp(snapshot)
    df = clean.copy()
    end = df["resolved_at"].fillna(snap)
    df["opened_date"] = df["opened_at"].dt.strftime("%Y-%m-%d")
    df["opened_month"] = df["opened_at"].dt.strftime("%Y-%m")
    df["resolved_date"] = df["resolved_at"].dt.strftime("%Y-%m-%d")
    df["is_resolved"] = df["resolved_at"].notna().astype(int)
    df["elapsed_hours"] = ((end - df["opened_at"]).dt.total_seconds() / 3600).round(2)
    df["response_hours"] = ((df["first_response_at"] - df["opened_at"]).dt.total_seconds()
                            / 3600).round(2)
    for col in ["opened_at", "first_response_at", "resolved_at", "closed_at", "updated_at"]:
        df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df[TICKET_COLUMNS]


def _rows(df: pd.DataFrame) -> list[tuple]:
    df = df.astype(object).where(df.notna(), None)
    return [tuple(r) for r in df.itertuples(index=False, name=None)]


def load(db: Database, result: QualityResult, run_id: str = "initial") -> None:
    """Create the schema, load the gated tickets and quality results, then create the views."""
    if db.dialect == "mysql":
        cur = db.conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for view in re.findall(r"CREATE VIEW (\w+)", read_sql("views.sql")):
            cur.execute(f"DROP VIEW IF EXISTS {view}")
        for table in ["dq_quarantine", "dq_check_results", "tickets", "service_category",
                      "sla_policy"]:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        db.conn.commit()
    db.execute_script(read_sql(f"schema_{db.dialect}.sql"))

    db.insert_many("sla_policy", ["priority", "priority_code", "response_target_hours",
                                  "resolution_target_hours", "sort_order"],
                   [(p.name, p.code, p.response_target_hours, p.resolution_target_hours, i + 1)
                    for i, p in enumerate(PRIORITIES)])
    db.insert_many("service_category", ["category", "resolver_group"],
                   [(c.name, c.group) for c in CATEGORIES])
    db.insert_many("tickets", TICKET_COLUMNS, _rows(ticket_frame(result.clean)))
    db.insert_many("dq_check_results",
                   ["run_id", "check_id", "dimension", "check_name", "rule_text", "action_taken",
                    "rows_flagged"],
                   [(run_id, c.id, c.dimension, c.name, c.rule, c.action, c.rows)
                    for c in result.checks])
    q = result.quarantine
    raw_cols = [c for c in q.columns if c != "dq_reason"]
    db.insert_many("dq_quarantine", ["ticket_id", "dq_reason", "raw_record"],
                   [(r["ticket_id"], r["dq_reason"], json.dumps({c: r[c] for c in raw_cols}))
                    for r in q.to_dict("records")])
    db.execute_script(read_sql("views.sql"))
