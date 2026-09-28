-- Reporting views. Written in the SQL subset MySQL 8 and SQLite 3.25+ share (CTEs and window
-- functions), so the dashboard, the Excel workbook and the Power BI model read identical logic.
--
-- SLA rules
--   * Resolution clock runs opened_at -> resolved_at in calendar hours (24x7 desk).
--   * A ticket is breached once elapsed time passes its priority's target: either it was
--     resolved late, or it is still open and already past target.
--   * Compliance = met / (met + breached). Open tickets still inside target are excluded
--     because their outcome is not known yet.

CREATE VIEW vw_ticket_sla AS
SELECT
    t.ticket_id, t.opened_at, t.first_response_at, t.resolved_at, t.closed_at, t.status,
    t.priority, p.priority_code, p.sort_order AS priority_order, t.category, t.subcategory,
    t.assignment_group, t.assigned_agent, t.channel, t.department, t.site,
    t.reassignment_count, t.reopened, t.wait_reason, t.dq_repaired,
    t.opened_date, t.opened_month, t.resolved_date, t.is_resolved, t.elapsed_hours,
    t.response_hours, p.resolution_target_hours, p.response_target_hours,
    CASE
        WHEN t.is_resolved = 1 AND t.elapsed_hours <= p.resolution_target_hours THEN 'Met'
        WHEN t.is_resolved = 1 THEN 'Breached'
        WHEN t.elapsed_hours > p.resolution_target_hours THEN 'Open - breached'
        ELSE 'Open - within SLA'
    END AS sla_state,
    CASE WHEN t.elapsed_hours > p.resolution_target_hours THEN 1 ELSE 0 END AS breached,
    CASE WHEN t.is_resolved = 0 AND t.elapsed_hours <= p.resolution_target_hours
         THEN 0 ELSE 1 END AS sla_scored,
    CASE
        WHEN t.response_hours IS NOT NULL AND t.response_hours <= p.response_target_hours THEN 1
        ELSE 0
    END AS response_met,
    CASE
        WHEN t.response_hours IS NULL AND t.elapsed_hours <= p.response_target_hours THEN 0
        ELSE 1
    END AS response_scored,
    CASE WHEN t.wait_reason <> '' THEN 1 ELSE 0 END AS waited_on_third_party,
    CASE
        WHEN t.reassignment_count = 0 THEN '0 hops'
        WHEN t.reassignment_count = 1 THEN '1 hop'
        ELSE '2+ hops'
    END AS hop_bucket
FROM tickets t
JOIN sla_policy p ON p.priority = t.priority;

-- Headline KPIs
CREATE VIEW vw_kpi_summary AS
SELECT
    COUNT(*) AS total_tickets,
    SUM(1 - is_resolved) AS open_backlog,
    SUM(CASE WHEN is_resolved = 0 AND breached = 1 THEN 1 ELSE 0 END) AS open_breached,
    SUM(breached) AS sla_breaches,
    ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)
        AS sla_compliance_pct,
    ROUND(100.0 * SUM(response_met) / NULLIF(SUM(response_scored), 0), 2)
        AS response_compliance_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours,
    ROUND(100.0 * SUM(CASE WHEN reassignment_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 2)
        AS reassigned_pct,
    ROUND(100.0 * SUM(reopened) / COUNT(*), 2) AS reopened_pct
FROM vw_ticket_sla;

-- Monthly cohort: tickets grouped by the month they were opened
CREATE VIEW vw_monthly_kpis AS
SELECT
    opened_month,
    COUNT(*) AS tickets_opened,
    SUM(breached) AS sla_breaches,
    ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)
        AS sla_compliance_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours,
    ROUND(100.0 * SUM(response_met) / NULLIF(SUM(response_scored), 0), 2)
        AS response_compliance_pct
FROM vw_ticket_sla
GROUP BY opened_month;

-- Daily flow and running backlog (tickets open at the end of each day)
CREATE VIEW vw_daily_backlog AS
WITH flow AS (
    SELECT opened_date AS flow_date, COUNT(*) AS opened, 0 AS resolved
    FROM tickets GROUP BY opened_date
    UNION ALL
    SELECT resolved_date, 0, COUNT(*)
    FROM tickets WHERE resolved_date IS NOT NULL GROUP BY resolved_date
),
daily AS (
    SELECT flow_date, SUM(opened) AS opened, SUM(resolved) AS resolved
    FROM flow GROUP BY flow_date
)
SELECT
    flow_date, opened, resolved,
    SUM(opened - resolved) OVER (ORDER BY flow_date ROWS BETWEEN UNBOUNDED PRECEDING
                                 AND CURRENT ROW) AS backlog
FROM daily;

-- Age profile of the open backlog at the snapshot
CREATE VIEW vw_backlog_aging AS
SELECT
    CASE
        WHEN elapsed_hours < 24 THEN '1. Under 1 day'
        WHEN elapsed_hours < 72 THEN '2. 1-3 days'
        WHEN elapsed_hours < 168 THEN '3. 3-7 days'
        WHEN elapsed_hours < 720 THEN '4. 7-30 days'
        ELSE '5. Over 30 days'
    END AS age_band,
    COUNT(*) AS open_tickets,
    SUM(breached) AS already_breached
FROM vw_ticket_sla
WHERE is_resolved = 0
GROUP BY
    CASE
        WHEN elapsed_hours < 24 THEN '1. Under 1 day'
        WHEN elapsed_hours < 72 THEN '2. 1-3 days'
        WHEN elapsed_hours < 168 THEN '3. 3-7 days'
        WHEN elapsed_hours < 720 THEN '4. 7-30 days'
        ELSE '5. Over 30 days'
    END;

-- Pareto of SLA breaches by category
CREATE VIEW vw_category_pareto AS
WITH c AS (
    SELECT category, COUNT(*) AS tickets, SUM(breached) AS breaches,
           SUM(sla_scored) AS scored
    FROM vw_ticket_sla GROUP BY category
)
SELECT
    category, tickets, breaches,
    ROUND(100.0 * breaches / NULLIF(scored, 0), 2) AS breach_rate_pct,
    ROUND(100.0 * tickets / SUM(tickets) OVER (), 2) AS share_of_volume_pct,
    ROUND(100.0 * breaches / SUM(breaches) OVER (), 2) AS share_of_breaches_pct,
    ROUND(100.0 * SUM(breaches) OVER (ORDER BY breaches DESC, category
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(breaches) OVER (), 2) AS cumulative_share_pct,
    ROW_NUMBER() OVER (ORDER BY breaches DESC, category) AS breach_rank
FROM c;

-- Compliance by priority against each target
CREATE VIEW vw_priority_sla AS
SELECT
    priority, priority_code, priority_order, resolution_target_hours, response_target_hours,
    COUNT(*) AS tickets, SUM(breached) AS breaches,
    ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)
        AS sla_compliance_pct,
    ROUND(100.0 * SUM(response_met) / NULLIF(SUM(response_scored), 0), 2)
        AS response_compliance_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours
FROM vw_ticket_sla
GROUP BY priority, priority_code, priority_order, resolution_target_hours,
         response_target_hours;

-- Category x priority breach matrix
CREATE VIEW vw_category_priority AS
SELECT
    category, priority, priority_order, COUNT(*) AS tickets, SUM(breached) AS breaches,
    ROUND(100.0 * SUM(breached) / NULLIF(SUM(sla_scored), 0), 2) AS breach_rate_pct
FROM vw_ticket_sla
GROUP BY category, priority, priority_order;

-- What sits behind a breach: third-party waits and hand-offs between groups
CREATE VIEW vw_breach_drivers AS
SELECT
    category, waited_on_third_party, hop_bucket,
    COUNT(*) AS tickets, SUM(breached) AS breaches,
    ROUND(100.0 * SUM(breached) / NULLIF(SUM(sla_scored), 0), 2) AS breach_rate_pct
FROM vw_ticket_sla
GROUP BY category, waited_on_third_party, hop_bucket;

-- Subcategories inside each category
CREATE VIEW vw_subcategory_breaches AS
SELECT
    category, subcategory, COUNT(*) AS tickets, SUM(breached) AS breaches,
    ROUND(100.0 * SUM(breached) / NULLIF(SUM(sla_scored), 0), 2) AS breach_rate_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours
FROM vw_ticket_sla
GROUP BY category, subcategory;

-- Resolver group workload
CREATE VIEW vw_group_workload AS
SELECT
    assignment_group, COUNT(*) AS tickets, SUM(1 - is_resolved) AS open_tickets,
    SUM(breached) AS breaches,
    ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)
        AS sla_compliance_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours,
    ROUND(AVG(reassignment_count), 2) AS avg_reassignments
FROM vw_ticket_sla
GROUP BY assignment_group;

-- Agent scorecard
CREATE VIEW vw_agent_scorecard AS
SELECT
    assigned_agent, assignment_group, COUNT(*) AS tickets,
    SUM(1 - is_resolved) AS open_tickets, SUM(breached) AS breaches,
    ROUND(100.0 * SUM(sla_scored - breached) / NULLIF(SUM(sla_scored), 0), 2)
        AS sla_compliance_pct,
    ROUND(AVG(CASE WHEN is_resolved = 1 THEN elapsed_hours END), 2) AS avg_resolution_hours
FROM vw_ticket_sla
GROUP BY assigned_agent, assignment_group;

-- Data-quality results of the latest load
CREATE VIEW vw_dq_summary AS
SELECT dimension, action_taken, SUM(rows_flagged) AS rows_flagged, COUNT(*) AS checks
FROM dq_check_results
GROUP BY dimension, action_taken;
