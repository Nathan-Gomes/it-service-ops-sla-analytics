# IT Service Ops & SLA Analytics Platform

**An analytics platform for a service desk: 50,000 simulated tickets pass through an automated data-quality gate into MySQL/SQLite reporting views, then out to a live dashboard, an Excel report and a Power BI model that monitor volume, backlog, resolution time and SLA compliance.**

[Open the dashboard](https://service-ops-sla.onrender.com) · [Read the case study](https://www.nathan-gomes.com/Project-Service-Ops-SLA.dc.html) · [Methodology](docs/METHODOLOGY.md) · [API reference](https://service-ops-sla.onrender.com/api/docs) · [Excel report](reports/service_ops_sla_report.xlsx)

[![Tests](https://github.com/Nathan-Gomes/it-service-ops-sla-analytics/actions/workflows/test.yml/badge.svg)](https://github.com/Nathan-Gomes/it-service-ops-sla-analytics/actions/workflows/test.yml)

![Python](https://img.shields.io/badge/Python-0d1117?style=for-the-badge&logo=python&logoColor=58a6ff)
![SQL](https://img.shields.io/badge/SQL-0d1117?style=for-the-badge&logo=sqlite&logoColor=74c0fc)
![MySQL](https://img.shields.io/badge/MySQL%208-0d1117?style=for-the-badge&logo=mysql&logoColor=4479a1)
![pandas](https://img.shields.io/badge/pandas-0d1117?style=for-the-badge&logo=pandas&logoColor=e70488)
![Power BI](https://img.shields.io/badge/Power%20BI-0d1117?style=for-the-badge&logo=powerbi&logoColor=f2c811)
![Excel](https://img.shields.io/badge/Excel-0d1117?style=for-the-badge&logo=microsoftexcel&logoColor=21a366)
![FastAPI](https://img.shields.io/badge/FastAPI-0d1117?style=for-the-badge&logo=fastapi&logoColor=009688)
![pytest](https://img.shields.io/badge/pytest-0d1117?style=for-the-badge&logo=pytest&logoColor=ffffff)

![Overview](docs/assets/overview.png)

---

## The finding

> **Access & Identity and Network & VPN carry 34% of ticket volume but 61% of SLA breaches.**

Together they breach 23.7% of scored tickets; the other six categories breach 7.7%. The cause is
the same in both queues: work that waits on someone outside the desk, and tickets that change hands.

| | Breach rate | Compared with |
|---|---:|---|
| Access & Identity tickets waiting on manager approval | **49.7%** | 13.6% without the wait |
| Network & VPN tickets handed off two or more times | **39.0%** | 19.5% when the first group kept them |
| Network & VPN tickets waiting on the carrier or vendor | **60.3%** | 18.2% without the wait |

If both queues breached at the rest of the desk's rate, compliance would rise from **86.9% to
92.3%**, clearing the 90% objective. That becomes three recommendations, each with an owner:

1. **Take approval off the critical path.** Pre-approved, role-based access bundles for common
   requests, plus approver reminders at 50% of target and escalation to a delegate at 75%.
2. **Route connectivity tickets straight to Network Operations.** Portal and email rules on
   creation, plus a response-time clause with the carrier so vendor waits have a ceiling.
3. **Watch both queues.** An at-risk alert at 75% of target and a weekly review until their breach
   rate is within two points of the desk average.

The data is simulated, so the finding holds by construction; [the methodology](docs/METHODOLOGY.md)
says exactly how. What carries over to a real desk is the pipeline and the method: Pareto, then
mechanism, then action.

![Breach analysis](docs/assets/breaches.png)

## How it works

```
simulate.py          50,000 tickets, Jan 2024 – Jun 2026, with queue pressure, hand-offs,
    │                third-party waits and four dated incidents
    ▼
export_raw()         50,950-row text export with 14 injected defect classes (answer key kept)
    │
    ▼
quality.py           15 checks: uniqueness → consistency → completeness → validity
    │                950 removed · 3,200 repaired · 520 quarantined → 49,480 clean tickets
    ▼
db.py + sql/         MySQL 8 or SQLite schema, then 13 reporting views in the SQL both share
    │                (CTEs, window functions); quality results land in dq_check_results
    ├──► analysis.py      Pareto, drivers, counterfactual, generated recommendations
    ├──► app.py           FastAPI + a dependency-free JavaScript dashboard (filtered SQL)
    ├──► excel.py         9-sheet workbook with Excel tables and native charts
    └──► pipeline.py      Power BI star schema (fact_ticket + 3 dimensions) + DAX measures
```

### The data-quality gate

Real exports are messy, so the raw file contains duplicates, stale re-exports, blank fields,
drifting labels (`IAM`, `VPN`, `P1`, `3 - Medium`) and impossible timelines. Every check either
repairs a record deterministically or quarantines it with a reason. Because the defects are
injected into known tickets, the tests assert that **each check finds exactly the injected rows**.

| Dimension | Checks | Action |
|---|---|---|
| Uniqueness | exact duplicates, superseded versions of a ticket | removed (950) |
| Consistency | non-standard category and priority labels | repaired (2,800) |
| Completeness | category inferred from subcategory; group from routing rule | repaired (400) |
| Completeness | missing priority or opened time | quarantined (165) |
| Validity | opened after export, resolved/responded before opened, closed before resolved, status contradicts timestamps | quarantined (355) |

![Data quality](docs/assets/quality.png)

### SLA rules

| Priority | First response | Resolution |
|---|---:|---:|
| P1 Critical | 15 min | 4 h |
| P2 High | 1 h | 8 h |
| P3 Medium | 4 h | 24 h |
| P4 Low | 8 h | 72 h |

A ticket is **breached** once elapsed time passes its target, whether it was resolved late or is
still open past target. **Compliance** = met ÷ (met + breached); open tickets still inside target
are not scored yet. The rules live once in `vw_ticket_sla`, and the tests hold the SQL views, the
dashboard's filtered queries and an independent pandas recomputation to the same numbers.

## The dashboard

| View | What it shows |
|---|---|
| **Overview** | KPI strip (tickets, SLA and first-response compliance against the 90% goal, median and 90th-percentile resolution, backlog, reassignment), monthly volume, monthly compliance, daily backlog, backlog age, performance by priority |
| **Breach analysis** | Generated finding, share of tickets vs share of breaches, category × priority breach-rate heatmap, Pareto table, wait and hand-off drivers for the two focus queues, worst subcategories, recommendations |
| **Queues & agents** | Resolver group workload and compliance, agent scorecard |
| **Data quality** | Gate totals, every check with its rule, action and examples, the quarantine with raw records, repairs applied |
| **Tickets** | All 49,480 tickets with SLA outcome; search, filter, sort, CSV export |

One filter bar (period, category, priority, group, site, channel) drives every view and lives in
the URL, so a filtered view can be shared as a link. Every chart has a hover or keyboard tooltip
and a table view, and there are light and dark themes.

![Tickets](docs/assets/tickets.png)

## Run it

```bash
pip install -e '.[dev]'
serviceops build          # simulate → gate → SQLite → Excel + Power BI export (about 3 s)
serviceops serve          # http://localhost:8000
python -m pytest -q       # 56 tests; the 9 MySQL ones need SERVICEOPS_MYSQL_URL
```

Load MySQL 8 instead of SQLite (the same schema and views):

```bash
pip install -e '.[mysql]'
serviceops build --db mysql://user:password@localhost/it_service_ops
```

Outputs land in `output/`: the database, the raw export, `quarantine.csv`,
`quality_report.json`, `findings.json`, `service_ops_sla_report.xlsx` and `powerbi/`.
`python scripts/publish_reports.py` refreshes the copies committed in [`reports/`](reports) and the
1,000-row [raw export sample](data/sample_raw_export.csv).

## Repository

```
src/serviceops/
  taxonomy.py       categories, priorities, SLA targets, label aliases
  simulate.py       ticket history and the defective export
  quality.py        the data-quality gate
  db.py             SQLite / MySQL loader
  sql/              schema_mysql.sql, schema_sqlite.sql, views.sql, reporting_queries.sql
  queries.py        filtered versions of the views for the dashboard
  analysis.py       finding, drivers, counterfactual, recommendations
  excel.py          Excel report
  pipeline.py       end-to-end build and Power BI export
  app.py            FastAPI service
  static/           dashboard (HTML, CSS, JavaScript; no framework)
powerbi/            DAX measures, theme and model guide
reports/            committed Excel report, quality report and findings
tests/              simulation, quality gate, SQL parity, findings, API, MySQL 8
```

CI runs lint, the full suite against SQLite **and a MySQL 8 service container**, and a complete
MySQL build on every push.

## Limits

- The tickets are simulated. The 61% is a property of the generator, not an observation about a
  real organisation.
- SLA clocks run in calendar hours and do not pause for "Pending customer"; business-hours
  calendars and clock pauses are the natural next step.
- The compliance counterfactual is an upper bound, not a forecast: it assumes the two queues could
  behave like the rest of the desk.
