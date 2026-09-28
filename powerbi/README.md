# Power BI model

`serviceops build` writes a star schema to `output/powerbi/`:

| Table | Grain | Key |
|---|---|---|
| `fact_ticket.csv` | one quality-gated ticket | `ticket_id` |
| `dim_date.csv` | one calendar day | `date` |
| `dim_priority.csv` | one priority with its response and resolution targets | `priority` |
| `dim_category.csv` | one service category with its resolver group | `category` |
| `dq_checks.csv` | one data-quality check from the latest load | `id` |

## Build the report (Power BI Desktop)

1. **Get data → Text/CSV** and load the five files (or **Get data → MySQL database** and pick
   `tickets`, `sla_policy`, `service_category`, `dq_check_results` if you loaded MySQL with
   `serviceops build --db mysql://...`).
2. **Model view**: relate `fact_ticket[priority]` → `dim_priority[priority]`,
   `fact_ticket[category]` → `dim_category[category]`, `fact_ticket[opened_date]` → `dim_date[date]`
   (many-to-one, single direction). Mark `dim_date` as the date table.
3. Paste the calculated columns and measures from [`measures.dax`](measures.dax).
4. **View → Themes → Browse** and load [`theme.json`](theme.json) (the dashboard's palette).
5. Suggested pages, matching the web dashboard:
   - *Overview*: cards for `Tickets`, `SLA Compliance %` (conditional colour on
     `Compliance vs Goal`), `Response Compliance %`, `Median Resolution (h)`, `Open Backlog`;
     a column chart of `Tickets` by `dim_date[month]`; a line of `SLA Compliance %` by month with
     a constant line at 90%; `Backlog EOD` by date.
   - *Breach analysis*: clustered bar of `Share of Tickets %` and `Share of Breaches %` by
     category; a table sorted by `SLA Breaches` with `Cumulative Breach Share %`; a matrix of
     `Breach Rate %` (category × priority) with background colour scale.
   - *Data quality*: a table of `dq_checks`.

Every measure mirrors a SQL view in `src/serviceops/sql/views.sql`, and the tests hold the SQL and
Python paths to the same numbers, so a Power BI page built this way reconciles with the Excel
report and the web dashboard.
