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


def movement(delta: float | None, *, pp: bool = False) -> str:
    """Describe changes at the same precision as displayed in the lesson."""
    if delta is None:
        return "has no percentage comparison (zero or missing baseline)"
    amount = round(delta if pp else 100 * delta, 1)
    if amount == 0:
        return "was unchanged at display precision"
    unit = " percentage points" if pp else "%"
    verb = "rose" if amount > 0 else "fell"
    return f"{verb} {abs(amount):.1f}{unit}"


def relative_change(first: float, last: float) -> float | None:
    return last / first - 1 if first else None


def describe_run(weekly: list[dict], channels: list[dict]) -> dict[str, str]:
    first, last = weekly[0], weekly[-1]
    signups = relative_change(first["signups"], last["signups"])
    revenue = relative_change(first["revenue_usd"], last["revenue_usd"])
    overall = 100 * (last["activation_rate"] - first["activation_rate"])
    volume = (f"From {first['week_start']} to {last['week_start']}, weekly signups "
              f"{movement(signups)} and revenue {movement(revenue)}.")
    activation = f"Overall activation {movement(overall, pp=True)}."
    ordered = sorted(channels, key=lambda r: (-r["activation_rate_change_pp"], r["acquisition_channel"]))
    comparison = "\n".join(
        f"- {r['acquisition_channel']} activation {movement(r['activation_rate_change_pp'], pp=True)}; "
        f"revenue {movement(r['revenue_growth'])}."
        for r in ordered
    )
    falling = [r["acquisition_channel"] for r in ordered if round(r["activation_rate_change_pp"], 1) < 0]
    followup = (
        "Inspect the activation declines in " + ", ".join(falling) +
        " before attributing them to a campaign or onboarding change."
        if falling else
        "No channel has a first-to-last activation decline at the displayed precision. "
        "Check intermediate weeks before inferring a steady trend."
    )
    support = (f"Support intensity starts at {first['tickets_per_100_signups']:.2f} and "
               f"ends at {last['tickets_per_100_signups']:.2f} tickets per 100 signups.")
    return {"volume": volume, "activation": activation, "channels": comparison,
            "followup": followup, "support": support}


def build_notebook(weekly: list[dict], channels: list[dict]) -> dict:
    story = describe_run(weekly, channels)
    cells = [
        notebook_cell(
            "markdown",
            "# Synthetic Product Growth Learning Lab\n\n"
            "This notebook uses the Data Analytics plugin's bundled synthetic demo. "
            "It demonstrates a reproducible SQLite workflow over a CSV snapshot.",
        ),
        notebook_cell(
            "markdown",
            f"## Results at a glance\n\n{story['volume']} {story['activation']}\n\n"
            + story["channels"],
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
            "## Takeaways\n\n" + story["followup"] +
            " Acquisition cost and retention are missing; these comparisons do not establish a budget decision.",
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
    headline_metrics = [
        {
            "latest_signups": last["signups"],
            "first_signups": first["signups"],
            "signup_growth": round(last["signups"] / first["signups"] - 1, 4),
            "latest_revenue": last["revenue_usd"],
            "first_revenue": first["revenue_usd"],
            "revenue_growth": relative_change(first["revenue_usd"], last["revenue_usd"]),
            "latest_activation_rate": last["activation_rate"],
            "first_activation_rate": first["activation_rate"],
            "activation_rate_change": round(last["activation_rate"] - first["activation_rate"], 4),
            "activation_rate_change_pp": round(
                100 * (last["activation_rate"] - first["activation_rate"]), 2
            ),
            "latest_tickets_per_100": last["tickets_per_100_signups"],
            "first_tickets_per_100": first["tickets_per_100_signups"],
            "ticket_intensity_growth": relative_change(
                first["tickets_per_100_signups"], last["tickets_per_100_signups"]
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
                f"Complete weeks from {first['week_start']} through {last['week_start']}",
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
                f"First week: {first['week_start']}",
                f"Last week: {last['week_start']}",
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
    story = describe_run(weekly, channels)
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Synthetic Product Growth: Compare volume and activation",
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
                    "subtitle": story["activation"],
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
                    "subtitle": "Percentage change from each channel’s own first-week revenue.",
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
                    "body": "# Synthetic Product Growth: Compare volume and activation",
                    "layout": "full",
                },
                {
                    "id": "executive-summary",
                    "type": "markdown",
                    "body": (
                        f"## Executive summary\n\n{story['volume']} {story['activation']}\n\n"
                        f"{story['followup']}"
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
                        f"## Volume and activation\n\n{story['volume']} {story['activation']} "
                        f"{story['support']} Inspect the weekly line for changes between the endpoints."
                    ),
                    "layout": "full",
                },
                {"id": "activation-chart-block", "type": "chart", "chartId": "activation-trend", "layout": "full"},
                {
                    "id": "channel-finding",
                    "type": "markdown",
                    "sourceId": "channel-growth-query",
                    "body": (
                        "## Channel observations\n\n"
                        "Ordered by first-to-last change in activation rate:\n\n" + story["channels"]
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
                        "## Recommended next steps\n\n" + story["followup"] +
                        " Compare signup-to-paid rate, cost and retention before proposing a scaling test."
                    ),
                    "layout": "full",
                },
                {
                    "id": "further-questions",
                    "type": "markdown",
                    "body": (
                        "## Further Questions\n\n"
                        "- Did the campaign, device or geographic mix change within a channel?\n"
                        "- Are support tickets concentrated in onboarding, billing, or product defects?\n"
                        "- How would 30- or 60-day retention change the comparison?\n"
                        "- What is customer acquisition cost by channel, and does it support a scaling test?"
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
                        "a future allocation decision.\n"
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
    # Validate the documented exercise shape, not the original answers.
    unique_keys = connection.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT week_start, acquisition_channel FROM product_growth)"
    ).fetchone()[0]
    if ((source_row_count, len(weekly), len(channels)) != (32, 8, 4)
            or unique_keys != source_row_count):
        raise ValueError("Expected one row per channel per week (4 channels × 8 weeks).")
    if connection.execute("SELECT COUNT(*) FROM product_growth WHERE signups <= 0").fetchone()[0]:
        raise ValueError("Each channel/week needs positive signups to calculate an activation rate.")
    source_signups = connection.execute("SELECT SUM(signups) FROM product_growth").fetchone()[0]
    if sum(row["signups"] for row in weekly) != source_signups:
        raise ValueError("Weekly signups did not reconcile to the input rows.")
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
            "unique_channel_week": "passed",
            "positive_signup_denominators": "passed",
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    notebook = build_notebook(weekly, channels)
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
