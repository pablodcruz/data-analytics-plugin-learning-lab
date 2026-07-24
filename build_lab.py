from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "sample-product-growth.csv"
NOTEBOOK_PATH = ROOT / "product-growth-analysis.ipynb"
RESULTS_PATH = ROOT / "analysis-results.json"
ARTIFACT_PATH = ROOT / "artifact.json"

WEEKLY_SQL = """
SELECT
  week_start,
  SUM(signups) AS signups,
  SUM(activated_users) AS activated_users,
  ROUND(1.0 * SUM(activated_users) / SUM(signups), 4) AS activation_rate,
  SUM(paid_conversions) AS paid_conversions,
  ROUND(1.0 * SUM(paid_conversions) / SUM(signups), 4) AS signup_to_paid_rate,
  SUM(revenue_usd) AS revenue_usd,
  SUM(support_tickets) AS support_tickets,
  ROUND(100.0 * SUM(support_tickets) / SUM(signups), 2) AS tickets_per_100_signups
FROM product_growth
GROUP BY week_start
ORDER BY week_start
""".strip()

CHANNEL_SQL = """
WITH channel_baselines AS (
  SELECT
    acquisition_channel,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_signups,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_signups,
    1.0 * MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN activated_users END)
      / MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_activation_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN activated_users END)
      / MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_activation_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN paid_conversions END)
      / MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_paid_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN paid_conversions END)
      / MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_paid_rate,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN revenue_usd END) AS first_revenue,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN revenue_usd END) AS last_revenue,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN support_tickets END) AS first_tickets,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN support_tickets END) AS last_tickets
  FROM product_growth
  GROUP BY acquisition_channel
)
SELECT
  acquisition_channel,
  first_signups,
  last_signups,
  ROUND(1.0 * last_signups / first_signups - 1, 4) AS signup_growth,
  ROUND(first_activation_rate, 4) AS first_activation_rate,
  ROUND(last_activation_rate, 4) AS last_activation_rate,
  ROUND(last_activation_rate - first_activation_rate, 4) AS activation_rate_change,
  ROUND(100.0 * (last_activation_rate - first_activation_rate), 2) AS activation_rate_change_pp,
  ROUND(first_paid_rate, 4) AS first_paid_rate,
  ROUND(last_paid_rate, 4) AS last_paid_rate,
  ROUND(last_paid_rate - first_paid_rate, 4) AS paid_rate_change,
  ROUND(100.0 * (last_paid_rate - first_paid_rate), 2) AS paid_rate_change_pp,
  first_revenue,
  last_revenue,
  ROUND(1.0 * last_revenue / first_revenue - 1, 4) AS revenue_growth,
  first_tickets,
  last_tickets,
  ROUND(1.0 * last_tickets / first_tickets - 1, 4) AS ticket_growth
FROM channel_baselines
ORDER BY revenue_growth DESC
""".strip()

PREVIEW_SQL = """
SELECT
  week_start,
  acquisition_channel,
  signups,
  activated_users,
  paid_conversions,
  revenue_usd,
  support_tickets
FROM product_growth
ORDER BY week_start, acquisition_channel
LIMIT 10
""".strip()


def load_database() -> tuple[sqlite3.Connection, int]:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE product_growth (
          week_start TEXT NOT NULL,
          acquisition_channel TEXT NOT NULL,
          signups INTEGER NOT NULL,
          activated_users INTEGER NOT NULL,
          paid_conversions INTEGER NOT NULL,
          revenue_usd REAL NOT NULL,
          support_tickets INTEGER NOT NULL
        )
        """
    )
    with DATA_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    connection.executemany(
        "INSERT INTO product_growth VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["week_start"],
                row["acquisition_channel"],
                int(row["signups"]),
                int(row["activated_users"]),
                int(row["paid_conversions"]),
                float(row["revenue_usd"]),
                int(row["support_tickets"]),
            )
            for row in rows
        ],
    )
    return connection, len(rows)


def query_rows(connection: sqlite3.Connection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def notebook_cell(cell_type: str, source: str) -> dict:
    cell = {
        "cell_type": cell_type,
        "metadata": {},
        "source": [line + "\n" for line in source.splitlines()],
    }
    if cell_type == "code":
        cell.update({"execution_count": None, "outputs": []})
    return cell


def execute_notebook(notebook: dict) -> None:
    namespace: dict = {"__name__": "__main__"}
    previous_cwd = Path.cwd()
    os.chdir(ROOT)
    try:
        execution_count = 0
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            execution_count += 1
            source = "".join(cell["source"])
            capture = io.StringIO()
            try:
                with contextlib.redirect_stdout(capture):
                    exec(compile(source, f"<notebook-cell-{execution_count}>", "exec"), namespace)
            except Exception as exc:
                cell["outputs"] = [
                    {
                        "output_type": "error",
                        "ename": type(exc).__name__,
                        "evalue": str(exc),
                        "traceback": [],
                    }
                ]
                raise
            text = capture.getvalue()
            cell["execution_count"] = execution_count
            cell["outputs"] = (
                [{"output_type": "stream", "name": "stdout", "text": [text]}]
                if text
                else []
            )
    finally:
        os.chdir(previous_cwd)


def build_notebook(first: dict, last: dict, paid_search: dict) -> dict:
    signup_growth = last["signups"] / first["signups"] - 1
    revenue_growth = last["revenue_usd"] / first["revenue_usd"] - 1
    activation_change = last["activation_rate"] - first["activation_rate"]
    cells = [
        notebook_cell(
            "markdown",
            "# Synthetic Product Growth Learning Lab\n\n"
            "This notebook uses the Data Analytics plugin's bundled synthetic demo. "
            "It demonstrates a reproducible SQLite workflow over a CSV snapshot.",
        ),
        notebook_cell(
            "markdown",
            "## tl;dr\n\n"
            f"- Weekly signups rose **{signup_growth:.1%}** and revenue rose "
            f"**{revenue_growth:.1%}** from the first to the last week.\n"
            f"- Overall activation fell **{abs(activation_change) * 100:.1f} percentage points**.\n"
            f"- Paid Search activation fell **{abs(paid_search['activation_rate_change_pp']):.1f} percentage points** "
            f"while support tickets rose **{paid_search['ticket_growth']:.0%}**, making it the clearest issue to investigate.",
        ),
        notebook_cell(
            "markdown",
            "## Context & Methods\n\n"
            "### Key Assumptions\n\n"
            "- Each row is one acquisition channel for one complete week.\n"
            "- Activation and paid-conversion rates use signups as the denominator.\n"
            "- First-to-last comparisons are descriptive; the synthetic data does not establish causality.",
        ),
        notebook_cell(
            "code",
            "import csv, json, sqlite3\n"
            "from pathlib import Path\n\n"
            "data_path = Path('sample-product-growth.csv')\n"
            "rows = list(csv.DictReader(data_path.open(newline='', encoding='utf-8')))\n"
            "connection = sqlite3.connect(':memory:')\n"
            "connection.execute('''CREATE TABLE product_growth (\n"
            "  week_start TEXT, acquisition_channel TEXT, signups INTEGER,\n"
            "  activated_users INTEGER, paid_conversions INTEGER,\n"
            "  revenue_usd REAL, support_tickets INTEGER)''')\n"
            "connection.executemany('INSERT INTO product_growth VALUES (?, ?, ?, ?, ?, ?, ?)', [\n"
            "  (r['week_start'], r['acquisition_channel'], int(r['signups']),\n"
            "   int(r['activated_users']), int(r['paid_conversions']),\n"
            "   float(r['revenue_usd']), int(r['support_tickets'])) for r in rows\n"
            "])\n"
            "print(f'Loaded {len(rows)} synthetic rows from {data_path.name}')",
        ),
        notebook_cell("markdown", "## Data\n\n### 1. Aggregate weekly funnel performance"),
        notebook_cell(
            "code",
            f"weekly_sql = {WEEKLY_SQL!r}\n"
            "cursor = connection.execute(weekly_sql)\n"
            "weekly_columns = [item[0] for item in cursor.description]\n"
            "weekly = [dict(zip(weekly_columns, row)) for row in cursor.fetchall()]\n"
            "print(json.dumps(weekly, indent=2))",
        ),
        notebook_cell("markdown", "## Results\n\n### 2. Compare channel quality and growth"),
        notebook_cell(
            "code",
            f"channel_sql = {CHANNEL_SQL!r}\n"
            "cursor = connection.execute(channel_sql)\n"
            "channel_columns = [item[0] for item in cursor.description]\n"
            "channels = [dict(zip(channel_columns, row)) for row in cursor.fetchall()]\n"
            "print(json.dumps(channels, indent=2))",
        ),
        notebook_cell(
            "markdown",
            "## Takeaways\n\n"
            "1. Preserve growth, but do not evaluate acquisition on signup volume alone.\n"
            "2. Investigate Paid Search targeting, landing pages, and onboarding because its volume rose while downstream quality deteriorated.\n"
            "3. Test incremental investment in Partners and Referral, where signup growth coincided with stronger activation and revenue.",
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def build_artifact(
    weekly: list[dict],
    channels: list[dict],
    preview: list[dict],
    generated_at: str,
) -> dict:
    first = weekly[0]
    last = weekly[-1]
    paid_search = next(row for row in channels if row["acquisition_channel"] == "Paid Search")
    headline_metrics = [
        {
            "latest_signups": last["signups"],
            "first_signups": first["signups"],
            "signup_growth": round(last["signups"] / first["signups"] - 1, 4),
            "latest_revenue": last["revenue_usd"],
            "first_revenue": first["revenue_usd"],
            "revenue_growth": round(last["revenue_usd"] / first["revenue_usd"] - 1, 4),
            "latest_activation_rate": last["activation_rate"],
            "first_activation_rate": first["activation_rate"],
            "activation_rate_change": round(last["activation_rate"] - first["activation_rate"], 4),
            "activation_rate_change_pp": round(
                100 * (last["activation_rate"] - first["activation_rate"]), 2
            ),
            "latest_tickets_per_100": last["tickets_per_100_signups"],
            "first_tickets_per_100": first["tickets_per_100_signups"],
            "ticket_intensity_growth": round(
                last["tickets_per_100_signups"] / first["tickets_per_100_signups"] - 1,
                4,
            ),
        }
    ]
    weekly_source = {
        "id": "weekly-growth-query",
        "label": "Synthetic product-growth demo — weekly summary",
        "path": "data-analytics-lab/sample-product-growth.csv",
        "query": {
            "engine": "SQLite",
            "language": "SQL",
            "description": "Aggregate the synthetic channel rows into weekly funnel, revenue, and support metrics.",
            "sql": WEEKLY_SQL,
            "tables_used": ["product_growth"],
            "filters": [
                "Complete weeks from 2026-04-06 through 2026-05-25",
                "All four acquisition channels",
                "Synthetic fixture data",
            ],
            "metric_definitions": [
                "Activation rate = activated users / signups for each week.",
                "Signup-to-paid rate = paid conversions / signups for each week.",
                "Tickets per 100 signups = 100 × support tickets / signups for each week.",
                "Revenue is the sum of revenue_usd in USD for each complete week.",
            ],
            "executed_at": generated_at,
        },
    }
    channel_source = {
        "id": "channel-growth-query",
        "label": "Synthetic product-growth demo — channel comparison",
        "path": "data-analytics-lab/sample-product-growth.csv",
        "query": {
            "engine": "SQLite",
            "language": "SQL",
            "description": "Compare first and last complete weeks for each acquisition channel.",
            "sql": CHANNEL_SQL,
            "tables_used": ["product_growth"],
            "filters": [
                "First week: 2026-04-06",
                "Last week: 2026-05-25",
                "Synthetic fixture data",
            ],
            "metric_definitions": [
                "Revenue growth = last-week revenue / first-week revenue − 1.",
                "Activation-rate change = last-week activation rate − first-week activation rate.",
                "Paid-rate change = last-week paid conversions/signups − first-week paid conversions/signups.",
                "Ticket growth = last-week support tickets / first-week support tickets − 1.",
            ],
            "executed_at": generated_at,
        },
    }
    preview_source = {
        "id": "raw-growth-preview",
        "label": "Synthetic product-growth demo — source preview",
        "path": "data-analytics-lab/sample-product-growth.csv",
        "query": {
            "engine": "SQLite",
            "language": "SQL",
            "description": "Show a deterministic ten-row preview at the source grain.",
            "sql": PREVIEW_SQL,
            "tables_used": ["product_growth"],
            "filters": ["First 10 rows ordered by week and acquisition channel"],
            "executed_at": generated_at,
        },
    }
    sources = [weekly_source, channel_source, preview_source]
    signup_growth = headline_metrics[0]["signup_growth"]
    revenue_growth = headline_metrics[0]["revenue_growth"]
    activation_change = headline_metrics[0]["activation_rate_change"]
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Synthetic Product Growth: Scale the winners, fix Paid Search",
            "description": "A hands-on Data Analytics learning lab built from synthetic product-growth data.",
            "generatedAt": generated_at,
            "sources": sources,
            "cards": [
                {
                    "id": "latest-signups",
                    "dataset": "headline_metrics",
                    "sourceId": "weekly-growth-query",
                    "description": "Total signups in the latest complete week, with first-week context.",
                    "metrics": [
                        {"label": "Latest signups", "field": "latest_signups", "format": "compact"},
                        {"label": "First week", "field": "first_signups", "format": "compact"},
                        {"label": "Change", "field": "signup_growth", "format": "percent", "signed": True},
                    ],
                },
                {
                    "id": "latest-revenue",
                    "dataset": "headline_metrics",
                    "sourceId": "weekly-growth-query",
                    "description": "Revenue in the latest complete week in USD, with first-week context.",
                    "metrics": [
                        {"label": "Latest revenue", "field": "latest_revenue", "format": "currency"},
                        {"label": "First week", "field": "first_revenue", "format": "currency"},
                        {"label": "Change", "field": "revenue_growth", "format": "percent", "signed": True},
                    ],
                },
                {
                    "id": "latest-activation",
                    "dataset": "headline_metrics",
                    "sourceId": "weekly-growth-query",
                    "description": "Activated users divided by signups in the latest complete week.",
                    "metrics": [
                        {"label": "Activation rate", "field": "latest_activation_rate", "format": "percent"},
                        {"label": "First week", "field": "first_activation_rate", "format": "percent"},
                        {"label": "Change (pp)", "field": "activation_rate_change_pp", "format": "number", "signed": True},
                    ],
                },
                {
                    "id": "latest-support-intensity",
                    "dataset": "headline_metrics",
                    "sourceId": "weekly-growth-query",
                    "description": "Support tickets per 100 signups in the latest complete week.",
                    "metrics": [
                        {"label": "Tickets / 100", "field": "latest_tickets_per_100", "format": "number"},
                        {"label": "First week", "field": "first_tickets_per_100", "format": "number"},
                        {"label": "Change", "field": "ticket_intensity_growth", "format": "percent", "signed": True},
                    ],
                },
            ],
            "charts": [
                {
                    "id": "activation-trend",
                    "title": "Weekly activation rate",
                    "subtitle": "Activation peaked in late April before declining for four consecutive weeks.",
                    "type": "line",
                    "intent": "trend",
                    "question": "Is acquisition growth translating into activated users?",
                    "dataset": "weekly_summary",
                    "sourceId": "weekly-growth-query",
                    "encodings": {
                        "x": {"field": "week_start", "type": "temporal", "label": "Week"},
                        "y": {
                            "field": "activation_rate",
                            "type": "quantitative",
                            "format": "percent",
                            "label": "Activation rate",
                        },
                        "tooltip": [
                            {"field": "signups", "type": "quantitative", "label": "Signups"},
                            {"field": "activated_users", "type": "quantitative", "label": "Activated users"},
                            {"field": "paid_conversions", "type": "quantitative", "label": "Paid conversions"},
                            {"field": "support_tickets", "type": "quantitative", "label": "Support tickets"},
                        ],
                    },
                    "valueFormat": "percent",
                    "layout": "full",
                    "labels": {"values": "endpoints"},
                    "palette": {"kind": "sequential", "name": "blue"},
                    "settings": {"showPoints": "always"},
                    "surface": {"surface": "card", "showControls": True, "viewMode": "both"},
                },
                {
                    "id": "channel-revenue-growth",
                    "title": "First-to-last-week revenue growth",
                    "subtitle": "Partners and Referral expanded while Paid Search finished below its starting revenue.",
                    "type": "bar",
                    "intent": "comparison",
                    "question": "Which acquisition channels converted growth into revenue?",
                    "dataset": "channel_summary",
                    "sourceId": "channel-growth-query",
                    "encodings": {
                        "x": {
                            "field": "acquisition_channel",
                            "type": "nominal",
                            "label": "Acquisition channel",
                        },
                        "y": {
                            "field": "revenue_growth",
                            "type": "quantitative",
                            "format": "percent",
                            "label": "Revenue growth",
                        },
                        "tooltip": [
                            {"field": "first_revenue", "type": "quantitative", "format": "currency", "label": "First-week revenue"},
                            {"field": "last_revenue", "type": "quantitative", "format": "currency", "label": "Last-week revenue"},
                            {"field": "activation_rate_change_pp", "type": "quantitative", "format": "number", "unit": "pp", "label": "Activation-rate change"},
                            {"field": "ticket_growth", "type": "quantitative", "format": "percent", "label": "Ticket growth"},
                        ],
                    },
                    "layout": "full",
                    "valueFormat": "percent",
                    "labels": {"values": "all"},
                    "palette": {"kind": "diverging", "name": "blue-orange", "midpoint": 0},
                    "referenceLines": [
                        {"axis": "y", "value": 0, "label": "No change", "color": "neutral", "lineStyle": "dashed"}
                    ],
                    "settings": {"orientation": "horizontal", "sort": "descending", "showValues": True},
                    "surface": {"surface": "card", "showControls": True, "viewMode": "both"},
                },
            ],
            "tables": [
                {
                    "id": "channel-scorecard",
                    "title": "Channel performance scorecard",
                    "subtitle": "First-to-last complete-week changes; rate changes are percentage-point differences.",
                    "dataset": "channel_summary",
                    "sourceId": "channel-growth-query",
                    "layout": "full",
                    "density": "spacious",
                    "defaultSort": {"field": "revenue_growth", "direction": "desc"},
                    "columns": [
                        {"field": "acquisition_channel", "label": "Channel", "type": "text"},
                        {"field": "signup_growth", "label": "Signup growth", "format": "percent", "movement": True},
                        {"field": "activation_rate_change_pp", "label": "Activation Δ (pp)", "format": "number", "movement": True},
                        {"field": "paid_rate_change_pp", "label": "Paid-rate Δ (pp)", "format": "number", "movement": True},
                        {"field": "revenue_growth", "label": "Revenue growth", "format": "percent", "movement": True},
                        {"field": "ticket_growth", "label": "Ticket growth", "format": "percent", "movement": True},
                    ],
                },
                {
                    "id": "source-preview",
                    "title": "Source data preview",
                    "subtitle": "Ten deterministic rows at one channel per complete week.",
                    "dataset": "raw_preview",
                    "sourceId": "raw-growth-preview",
                    "layout": "full",
                    "density": "dense",
                    "defaultSort": {"field": "week_start", "direction": "asc"},
                    "columns": [
                        {"field": "week_start", "label": "Week", "type": "date"},
                        {"field": "acquisition_channel", "label": "Channel", "type": "text"},
                        {"field": "signups", "label": "Signups", "format": "number"},
                        {"field": "activated_users", "label": "Activated", "format": "number"},
                        {"field": "paid_conversions", "label": "Paid", "format": "number"},
                        {"field": "revenue_usd", "label": "Revenue", "format": "currency"},
                        {"field": "support_tickets", "label": "Tickets", "format": "number"},
                    ],
                },
            ],
            "blocks": [
                {
                    "id": "report-title",
                    "type": "markdown",
                    "body": "# Synthetic Product Growth: Scale the winners, fix Paid Search",
                    "layout": "full",
                },
                {
                    "id": "executive-summary",
                    "type": "markdown",
                    "body": (
                        "## Executive Summary\n\n"
                        f"- **Top-line growth is strong.** Weekly signups increased **{signup_growth:.1%}** "
                        f"and revenue increased **{revenue_growth:.1%}** from April 6 to May 25.\n"
                        f"- **Funnel quality is weakening.** Overall activation fell "
                        f"**{abs(activation_change) * 100:.1f} percentage points**, even as acquisition volume increased.\n"
                        f"- **Paid Search is the clear drag.** Its activation rate fell "
                        f"**{abs(paid_search['activation_rate_change_pp']):.1f} percentage points**, revenue declined "
                        f"**{abs(paid_search['revenue_growth']):.1%}**, and support tickets rose "
                        f"**{paid_search['ticket_growth']:.0%}**.\n"
                        "- **Recommended action:** protect the healthy Organic base, test more investment in "
                        "Partners and Referral, and pause incremental Paid Search scaling until traffic quality "
                        "and onboarding are diagnosed."
                    ),
                    "layout": "full",
                },
                {
                    "id": "headline-kpis",
                    "type": "metric-strip",
                    "cardIds": [
                        "latest-signups",
                        "latest-revenue",
                        "latest-activation",
                        "latest-support-intensity",
                    ],
                    "layout": "full",
                },
                {
                    "id": "volume-quality-finding",
                    "type": "markdown",
                    "sourceId": "weekly-growth-query",
                    "body": (
                        "## Volume is rising while funnel quality is slipping\n\n"
                        "Signups increased every week, but activation peaked at **62.7%** on April 27 and "
                        "fell to **57.5%** by May 25. Support intensity moved the other way, rising from "
                        "**7.41** to **9.19 tickets per 100 signups**. The growth is real, but the business "
                        "is acquiring progressively more users who need help or do not reach activation."
                    ),
                    "layout": "full",
                },
                {"id": "activation-chart-block", "type": "chart", "chartId": "activation-trend", "layout": "full"},
                {
                    "id": "channel-finding",
                    "type": "markdown",
                    "sourceId": "channel-growth-query",
                    "body": (
                        "## Paid Search is the drag; Partners and Referral lead quality\n\n"
                        "Partners produced the fastest revenue growth (**77.1%**) while improving activation "
                        "by **5.3 points**. Referral revenue rose **56.2%** with a **5.1-point** activation gain. "
                        "Paid Search moved in the opposite direction: signups rose **47.2%**, but revenue fell "
                        "**18.3%**. That divergence makes Paid Search the highest-priority diagnostic, not the "
                        "highest-priority scaling channel."
                    ),
                    "layout": "full",
                },
                {"id": "channel-chart-block", "type": "chart", "chartId": "channel-revenue-growth", "layout": "full"},
                {
                    "id": "scorecard-intro",
                    "type": "markdown",
                    "body": (
                        "### Read the channel scorecard\n\n"
                        "Use the exact values below to compare scale and quality together. Positive signup growth "
                        "is only attractive when activation, paid conversion, and revenue also remain healthy."
                    ),
                    "layout": "full",
                },
                {"id": "channel-table-block", "type": "table", "tableId": "channel-scorecard", "layout": "full"},
                {
                    "id": "recommended-actions",
                    "type": "markdown",
                    "body": (
                        "## Recommended Next Steps\n\n"
                        "1. **Diagnose Paid Search before adding budget.** Split performance by campaign, keyword, "
                        "landing page, device, and geography; inspect whether the May decline is concentrated.\n"
                        "2. **Run controlled scaling tests for Partners and Referral.** Increase exposure in small "
                        "steps and monitor activation, paid conversion, revenue per signup, and support intensity.\n"
                        "3. **Protect Organic quality.** Organic remains the largest healthy source; monitor it as "
                        "the baseline while other channels change.\n"
                        "4. **Add guardrails.** Pair signup targets with activation rate and tickets per 100 signups "
                        "so volume cannot mask deteriorating acquisition quality."
                    ),
                    "layout": "full",
                },
                {
                    "id": "further-questions",
                    "type": "markdown",
                    "body": (
                        "## Further Questions\n\n"
                        "- Did Paid Search mix shift toward a new campaign, keyword group, device, or geography?\n"
                        "- Are support tickets concentrated in onboarding, billing, or product defects?\n"
                        "- Do Partners and Referral retain their advantage after 30- or 60-day retention is added?\n"
                        "- What is customer acquisition cost by channel, and does it change the scaling recommendation?"
                    ),
                    "layout": "full",
                },
                {
                    "id": "source-preview-intro",
                    "type": "markdown",
                    "body": (
                        "## Explore the Underlying Rows\n\n"
                        "This preview exposes the dataset grain used by the SQL: one acquisition channel per complete "
                        "week. Open the source controls on cards, charts, and tables to inspect definitions and queries."
                    ),
                    "layout": "full",
                },
                {"id": "source-preview-block", "type": "table", "tableId": "source-preview", "layout": "full"},
                {
                    "id": "caveats",
                    "type": "markdown",
                    "body": (
                        "## Caveats and Assumptions\n\n"
                        "- The dataset is synthetic and demonstrates workflow mechanics rather than a real company result.\n"
                        "- There are only eight complete weeks, so findings are descriptive and not causal.\n"
                        "- Acquisition cost, retention, campaign mix, and ticket categories are absent; each could change "
                        "the recommended allocation.\n"
                        "- Rates use signups as the denominator, and no rows are excluded."
                    ),
                    "layout": "full",
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "fixture",
            "datasets": {
                "headline_metrics": headline_metrics,
                "weekly_summary": weekly,
                "channel_summary": channels,
                "raw_preview": preview,
            },
        },
        "sources": sources,
    }


def main() -> None:
    connection, source_row_count = load_database()
    weekly = query_rows(connection, WEEKLY_SQL)
    channels = query_rows(connection, CHANNEL_SQL)
    preview = query_rows(connection, PREVIEW_SQL)
    assert source_row_count == 32
    assert len(weekly) == 8
    assert len(channels) == 4
    assert sum(row["signups"] for row in weekly) == 10189
    assert weekly[0]["week_start"] == "2026-04-06"
    assert weekly[-1]["week_start"] == "2026-05-25"
    assert round(weekly[-1]["activation_rate"], 4) == 0.5752
    paid_search = next(row for row in channels if row["acquisition_channel"] == "Paid Search")
    assert paid_search["revenue_growth"] == -0.1833
    generated_at = datetime.now(timezone.utc).isoformat()

    results = {
        "generated_at": generated_at,
        "source_row_count": source_row_count,
        "weekly_summary": weekly,
        "channel_summary": channels,
        "source_preview": preview,
        "validation": {
            "row_count": "passed",
            "week_count": "passed",
            "channel_count": "passed",
            "weekly_signup_reconciliation": "passed",
            "headline_spot_checks": "passed",
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    notebook = build_notebook(weekly[0], weekly[-1], paid_search)
    execute_notebook(notebook)
    assert notebook["nbformat"] == 4
    assert all(
        not any(output.get("output_type") == "error" for output in cell.get("outputs", []))
        for cell in notebook["cells"]
    )
    NOTEBOOK_PATH.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")

    artifact = build_artifact(weekly, channels, preview, generated_at)
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "source_rows": source_row_count,
                "weekly_rows": len(weekly),
                "channel_rows": len(channels),
                "notebook": NOTEBOOK_PATH.name,
                "artifact": ARTIFACT_PATH.name,
                "status": "ready_for_artifact_validation",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
