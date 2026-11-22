"""Render one synthetic comparison from two rebuilt Learning Lab reports."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import shutil
from string import Template
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
FIRST_WEEK, WEEK, CHANNEL = "2026-04-06", "2026-05-25", "Paid Search"
BASELINE, EDITED = 210, 500
SCALE = 40  # Shared plot viewport in percentage points.
SOURCE_FIXTURE_SHA256 = "7a417139cf77ba194f8d328db17ca08355edab76f1aef3bd8ef0e75863a6c0f5"
SCENARIOS = (("original", "A", "Original", BASELINE), ("edited", "B", "Edited", EDITED))


@dataclass(frozen=True)
class Reading:
    key: str
    letter: str
    name: str
    activated: int
    signups: int
    first_activated: int
    first_signups: int
    first_activation_rate: float
    last_activation_rate: float
    activation_pp: float
    overall_activation_pp: float
    revenue_fraction: float
    finding: str
    followup: str


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(type(value) in (float, int) and math.isfinite(value), "Expected finite report metrics.")
    return value


def report_readings(report, first_row, last_row, key, letter, name):
    require(report["surface"] == "report" and report["snapshot"]["status"] == "fixture",
            "Expected a generated report with a synthetic snapshot.")
    ds = report["snapshot"]["datasets"]
    weeks = ds["weekly_summary"]
    require((weeks[0]["week_start"], weeks[-1]["week_start"]) == (FIRST_WEEK, WEEK),
            "Expected the bundled reporting period.")
    paid, = [r for r in ds["channel_summary"] if r["acquisition_channel"] == CHANNEL]
    headline, = ds["headline_metrics"]
    blocks = {block["id"]: block.get("body", "") for block in report["manifest"]["blocks"]}
    finding, = [line.removeprefix("- ") for line in blocks["channel-finding"].splitlines()
                if line.startswith("- Paid Search activation")]
    followup = blocks["recommended-actions"].split("\n\n", 1)[1]
    def source_counts(row, expected_signups):
        activated, signups = (int(row[field]) for field in ("activated_users", "signups"))
        require(0 <= activated <= signups and signups == expected_signups,
                "The experiment row does not reconcile to the generated report.")
        return activated, signups

    first_activated, first_signups = source_counts(first_row, paid["first_signups"])
    activated, signups = source_counts(last_row, paid["last_signups"])
    return Reading(key, letter, name, activated, signups, first_activated, first_signups,
                   number(paid["first_activation_rate"]), number(paid["last_activation_rate"]),
                   number(paid["activation_rate_change_pp"]),
                   number(headline["activation_rate_change_pp"]), number(paid["revenue_growth"]),
                   finding, followup)


def endpoint_index(rows, week):
    index, = [i for i, row in enumerate(rows)
              if (row["week_start"], row["acquisition_channel"]) == (week, CHANNEL)]
    return index


def build_reports(source):
    # Hashes the fixture only, not the builder: approved builder improvements can remain reusable.
    require(sha256((source / "sample-product-growth.csv").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            == SOURCE_FIXTURE_SHA256, "Restore the original bundled synthetic CSV to run this example.")
    with (source / "sample-product-growth.csv").open(encoding="utf-8", newline="") as fixture:
        reader = csv.DictReader(fixture)
        rows, fields = list(reader), reader.fieldnames
    first_idx = endpoint_index(rows, FIRST_WEEK)
    idx = endpoint_index(rows, WEEK)
    require(rows[idx]["activated_users"] == str(BASELINE), "Expected the original fixture value.")
    results = []
    for key, letter, name, activated in SCENARIOS:
        run_rows = [dict(row) if i != idx else {**row, "activated_users": str(activated)}
                    for i, row in enumerate(rows)]
        with tempfile.TemporaryDirectory(prefix="learning-lab-report-") as tmp:
            sandbox = Path(tmp)
            shutil.copyfile(source / "build_lab.py", sandbox / "build_lab.py")
            with (sandbox / "sample-product-growth.csv").open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows(run_rows)
            subprocess.run([sys.executable, "build_lab.py"], cwd=sandbox, check=True, stdout=subprocess.DEVNULL)
            raw = (sandbox / "artifact.json").read_bytes()
            results.append((report_readings(json.loads(raw), run_rows[first_idx], run_rows[idx], key, letter, name), raw))
    original, edited = (reading for reading, _ in results)
    require(-SCALE <= original.activation_pp < 0 < edited.activation_pp <= SCALE
            and original.revenue_fraction == edited.revenue_fraction,
            "The generated reports do not match the one-cell experiment.")
    return results


def signed(value, precision=".1f"):
    return format(value, "+" + precision).replace("-", "−")


def render(scenarios, template):
    def bar(s):
        tone = "down" if s.activation_pp < 0 else "up"
        extent = 50 * abs(s.activation_pp) / SCALE  # Convert to length, not a new metric.
        return f"""<div class="plot-row {tone}">
      <div class="row-key"><span class="stamp">{s.letter}</span> {s.name}</div>
      <div class="track" aria-hidden="true"><span class="fill" style="--extent:{extent:.5f}%"></span></div>
      <div class="reading"><strong>{signed(s.activation_pp)}</strong> <abbr title="percentage points">pp</abbr></div>
    </div>"""

    def rate_endpoint(date, rate, activated, signups):
        return (f"<div><dt>{date}</dt><dd><strong>{rate:.2%}</strong>"
                f'<span class="rate-count">{activated} of {signups} signups</span></dd></div>')

    def rates(s):
        return f"""<div class="rate-card">
      <h3>{s.letter} · {s.name}</h3>
      <dl>
        {rate_endpoint("Apr 6", s.first_activation_rate, s.first_activated, s.first_signups)}
        {rate_endpoint("May 25", s.last_activation_rate, s.activated, s.signups)}
      </dl>
    </div>"""

    def condition(s):
        return f'<article class="input"><p class="label">{s.letter} / {s.name}</p><strong>{s.activated}</strong><span> of {s.signups} signups</span></article>'

    def check(s):
        return f'<tr><th scope="row">{s.letter} · {s.name}</th><td>{signed(s.overall_activation_pp)} pp</td><td>{signed(s.revenue_fraction, ".1%")}</td></tr>'

    def evidence(s):
        return f"""<article class="source">
        <h3>{s.letter} · {s.name} report</h3>
        <p>{escape(s.finding)}</p>
        <p>{escape(s.followup)}</p>
        <a href="reports/{s.key}-report.json">Open {s.name.lower()} report JSON</a>
    </article>"""

    return Template(template).substitute(
        inputs="\n".join(map(condition, scenarios)), bars="\n".join(map(bar, scenarios)),
        rates="\n".join(map(rates, scenarios)), checks="\n".join(map(check, scenarios)),
        evidence="\n".join(map(evidence, scenarios)),
    )


def generate(source, destination):
    results = build_reports(source)
    template = (source / "comparison.template.html").read_text(encoding="utf-8")
    html = render([reading for reading, _ in results], template)
    report_dir = destination / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    for reading, raw in results:
        (report_dir / f"{reading.key}-report.json").write_bytes(raw)
    output = destination / "index.html"
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    try:
        print(generate(ROOT, ROOT / ".comparison"))
    except (ValueError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        sys.exit(f"Cannot generate the synthetic comparison: {error}")
