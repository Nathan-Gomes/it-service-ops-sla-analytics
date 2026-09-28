-- IT Service Ops & SLA Analytics: SQLite schema (same tables as schema_mysql.sql).

CREATE TABLE sla_policy (
    priority                VARCHAR(10)  NOT NULL PRIMARY KEY,
    priority_code           CHAR(2)      NOT NULL,
    response_target_hours   REAL NOT NULL,
    resolution_target_hours REAL NOT NULL,
    sort_order              INTEGER      NOT NULL
);

CREATE TABLE service_category (
    category       VARCHAR(40) NOT NULL PRIMARY KEY,
    resolver_group VARCHAR(40) NOT NULL
);

CREATE TABLE tickets (
    ticket_id          VARCHAR(12)  NOT NULL PRIMARY KEY,
    opened_at          TEXT     NOT NULL,
    first_response_at  TEXT     NULL,
    resolved_at        TEXT     NULL,
    closed_at          TEXT     NULL,
    updated_at         TEXT     NULL,
    status             VARCHAR(12)  NOT NULL,
    priority           VARCHAR(10)  NOT NULL,
    category           VARCHAR(40)  NOT NULL,
    subcategory        VARCHAR(40)  NOT NULL,
    assignment_group   VARCHAR(40)  NOT NULL,
    assigned_agent     VARCHAR(40)  NOT NULL,
    channel            VARCHAR(10)  NOT NULL,
    department         VARCHAR(20)  NOT NULL,
    site               VARCHAR(20)  NOT NULL,
    reassignment_count INTEGER     NOT NULL,
    reopened           INTEGER      NOT NULL,
    wait_reason        VARCHAR(40)  NOT NULL,
    dq_repaired        VARCHAR(80)  NOT NULL,
    -- Derived at load so the views stay portable between MySQL and SQLite.
    opened_date        TEXT         NOT NULL,
    opened_month       CHAR(7)      NOT NULL,
    resolved_date      TEXT         NULL,
    is_resolved        INTEGER      NOT NULL,
    elapsed_hours      REAL NOT NULL,  -- opened -> resolved, or opened -> snapshot
    response_hours     REAL NULL,
    CONSTRAINT fk_tickets_priority FOREIGN KEY (priority) REFERENCES sla_policy (priority),
    CONSTRAINT fk_tickets_category FOREIGN KEY (category) REFERENCES service_category (category)
);

CREATE INDEX ix_tickets_opened_date ON tickets (opened_date);
CREATE INDEX ix_tickets_resolved_date ON tickets (resolved_date);
CREATE INDEX ix_tickets_category ON tickets (category, priority);
CREATE INDEX ix_tickets_group ON tickets (assignment_group);

CREATE TABLE dq_check_results (
    run_id       VARCHAR(20)  NOT NULL,
    check_id     VARCHAR(4)   NOT NULL,
    dimension    VARCHAR(20)  NOT NULL,
    check_name   VARCHAR(60)  NOT NULL,
    rule_text    VARCHAR(200) NOT NULL,
    action_taken VARCHAR(12)  NOT NULL,
    rows_flagged INT          NOT NULL,
    PRIMARY KEY (run_id, check_id)
);

CREATE TABLE dq_quarantine (
    ticket_id  VARCHAR(12) NOT NULL,
    dq_reason  VARCHAR(60) NOT NULL,
    raw_record TEXT        NOT NULL
);
