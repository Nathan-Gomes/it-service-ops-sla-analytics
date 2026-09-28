# Data dictionary

Tables and views created by `serviceops build` (schemas in
[`src/serviceops/sql/`](../src/serviceops/sql)). Types are MySQL 8; SQLite uses TEXT, INTEGER and
REAL for the same columns.

## `tickets` — one row per quality-gated ticket

| Column | Type | Meaning |
|---|---|---|
| `ticket_id` | VARCHAR(12) PK | `INC` + seven digits |
| `opened_at` | DATETIME | When the ticket was logged; starts both SLA clocks |
| `first_response_at` | DATETIME NULL | First agent response; NULL if none by the snapshot |
| `resolved_at` | DATETIME NULL | Resolution; stops the resolution clock. NULL while open |
| `closed_at` | DATETIME NULL | Auto-closed three days after resolution |
| `updated_at` | DATETIME | Last change in the source system; used to pick the newest copy of a re-exported ticket |
| `status` | VARCHAR(12) | Open, In Progress, Pending, Resolved, Closed |
| `priority` | VARCHAR(10) FK | Critical, High, Medium, Low → `sla_policy` |
| `category` | VARCHAR(40) FK | One of eight service categories → `service_category` |
| `subcategory` | VARCHAR(40) | Belongs to exactly one category (used to repair blank categories) |
| `assignment_group` | VARCHAR(40) | Resolver group that owns the ticket |
| `assigned_agent` | VARCHAR(40) | Agent within that group |
| `channel` | VARCHAR(10) | Portal, Email, Phone, Chat |
| `department`, `site` | VARCHAR(20) | Requester's department and location |
| `reassignment_count` | SMALLINT | Times the ticket moved between groups |
| `reopened` | TINYINT | 1 if reopened after a resolution |
| `wait_reason` | VARCHAR(40) | Third party the ticket waited on (approver, carrier, vendor, parts, HR, user); blank if none |
| `dq_repaired` | VARCHAR(80) | Repairs the quality gate applied, `;`-separated; blank if untouched |
| `opened_date`, `opened_month` | DATE, CHAR(7) | Derived at load for portable grouping |
| `resolved_date` | DATE NULL | Derived at load |
| `is_resolved` | TINYINT | 1 once `resolved_at` is set |
| `elapsed_hours` | DECIMAL(9,2) | Opened → resolved, or opened → snapshot for open tickets |
| `response_hours` | DECIMAL(9,2) NULL | Opened → first response |

## Reference and audit tables

| Table | Grain | Columns |
|---|---|---|
| `sla_policy` | priority | `priority`, `priority_code` (P1–P4), `response_target_hours`, `resolution_target_hours`, `sort_order` |
| `service_category` | category | `category`, `resolver_group` (the routing rule) |
| `dq_check_results` | check per load | `run_id`, `check_id`, `dimension`, `check_name`, `rule_text`, `action_taken`, `rows_flagged` |
| `dq_quarantine` | quarantined row | `ticket_id`, `dq_reason`, `raw_record` (the original export row as JSON) |
| `ticket_sla` | ticket | Output of `vw_ticket_sla` materialized at load and indexed; the dashboard's filtered queries read it |

## Views

| View | Grain | What it answers |
|---|---|---|
| `vw_ticket_sla` | ticket | Every ticket with its targets and SLA outcome: `sla_state` (Met, Breached, Open - breached, Open - within SLA), `breached`, `sla_scored`, `response_met`, `response_scored`, `waited_on_third_party`, `hop_bucket`. **The single definition of the SLA rules.** |
| `vw_kpi_summary` | one row | Tickets, open backlog, breaches, SLA and first-response compliance, average resolution, reassigned and reopened rates |
| `vw_monthly_kpis` | opened month | Volume, breaches, compliance and resolution time by cohort |
| `vw_daily_backlog` | day | Opened, resolved and running open backlog |
| `vw_backlog_aging` | age band | Open tickets and how many are already past target |
| `vw_category_pareto` | category | Breaches, breach rate, share of volume, share of breaches, cumulative share, rank |
| `vw_priority_sla` | priority | Compliance against each target |
| `vw_category_priority` | category × priority | Breach-rate matrix |
| `vw_breach_drivers` | category × wait × hand-offs | Breach rate by third-party wait and reassignment bucket |
| `vw_subcategory_breaches` | subcategory | Breaches inside each category |
| `vw_group_workload` | resolver group | Volume, open, breaches, compliance, average hand-offs |
| `vw_agent_scorecard` | agent | Volume, open, breaches, compliance |
| `vw_dq_summary` | dimension × action | Rows flagged by the quality gate |

## Measure definitions

| Measure | Definition |
|---|---|
| Breached | `elapsed_hours > resolution_target_hours` (resolved late, or open and already past target) |
| Scored | Resolved, or open and breached. Open tickets inside target are excluded until their outcome is known |
| SLA compliance | (scored − breached) ÷ scored |
| First-response compliance | responses within target ÷ responses scored (same rule on the response clock) |
| Breach rate | breached ÷ scored, within a group |
| Share of breaches | a group's breaches ÷ all breaches |
| Target used (watch list) | `elapsed_hours ÷ resolution_target_hours` for open tickets; flagged at 75% |
