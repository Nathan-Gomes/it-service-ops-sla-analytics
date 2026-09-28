-- Analyst queries over the reporting views. Each runs unchanged on MySQL 8 and SQLite.

-- 1. Headline KPIs
SELECT * FROM vw_kpi_summary;

-- 2. Pareto: which categories carry the breaches, and how many carry 60%+
SELECT breach_rank, category, tickets, breaches, breach_rate_pct,
       share_of_volume_pct, share_of_breaches_pct, cumulative_share_pct
FROM vw_category_pareto
ORDER BY breach_rank;

-- 3. Inside the top two categories: third-party waits and hand-offs
SELECT d.category, d.waited_on_third_party, d.hop_bucket, d.tickets, d.breaches,
       d.breach_rate_pct
FROM vw_breach_drivers d
JOIN vw_category_pareto p ON p.category = d.category
WHERE p.breach_rank <= 2
ORDER BY d.category, d.waited_on_third_party, d.hop_bucket;

-- 4. Monthly trend with a 3-month rolling compliance
SELECT opened_month, tickets_opened, sla_compliance_pct,
       ROUND(AVG(sla_compliance_pct) OVER (ORDER BY opened_month
             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS compliance_3m_avg
FROM vw_monthly_kpis
ORDER BY opened_month;

-- 5. Open tickets already past target, oldest first (the morning stand-up list)
SELECT ticket_id, opened_at, priority, category, assignment_group, assigned_agent,
       elapsed_hours, resolution_target_hours, wait_reason
FROM vw_ticket_sla
WHERE sla_state = 'Open - breached'
ORDER BY elapsed_hours DESC;

-- 6. Agents compared only within their own group
SELECT assignment_group, assigned_agent, tickets, sla_compliance_pct,
       RANK() OVER (PARTITION BY assignment_group ORDER BY sla_compliance_pct DESC)
           AS rank_in_group
FROM vw_agent_scorecard
ORDER BY assignment_group, rank_in_group;

-- 7. What the quality gate did on the latest load
SELECT check_id, dimension, check_name, action_taken, rows_flagged
FROM dq_check_results
ORDER BY check_id;
