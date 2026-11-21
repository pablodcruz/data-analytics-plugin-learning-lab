# Data Analytics Plugin Learning Lab

This lab uses the Data Analytics plugin's bundled **synthetic** product-growth
dataset. It is designed to show the full workflow without requiring a live
warehouse or exposing real business data.

## What's included

- `sample-product-growth.csv` — 32 source rows at one acquisition channel per week
- `analysis.sql` — the durable SQL used for weekly and channel-level analysis
- `product-growth-analysis.ipynb` — an executed, reader-friendly analysis notebook
- `analysis-results.json` — reviewed query outputs and data checks
- `artifact.json` — the canonical interactive report payload
- `build_lab.py` — rebuilds the notebook, results, and artifact from the CSV

## Rebuild the lab

From this folder:

```powershell
python .\build_lab.py
```

The script uses only Python's standard library and SQLite. It verifies the
expected row, week, and channel counts; reconciles weekly signups; executes the
notebook cells in order; and regenerates the report payload.

## Prompts to try

Paste one of these into a new Codex task and attach or reference
`sample-product-growth.csv`:

1. `@Data Analytics compare first- and last-week activation with signup growth; explain any divergence.`
2. `@Data Analytics compare acquisition channels and recommend where to invest.`
3. `@Data Analytics validate this dataset and identify analytical risks.`
4. `@Data Analytics build a KPI framework for acquisition quality.`
5. `@Data Analytics turn this into a dashboard with channel and week filters.`
6. `@Data Analytics create a reproducible notebook that tests whether support intensity tracks activation.`

## How to experiment

1. Change one or more values in the CSV.
2. Run `python .\build_lab.py`.
3. Ask Data Analytics to explain what changed and whether the recommendation still holds.
4. Ask for a different view: KPI report, dashboard, validation report, notebook, or chart.
5. Replace the synthetic CSV with your own file once the workflow feels familiar. The bundled builder expects four channels over eight weeks, one row per channel per week and positive signups. Run `python -m unittest -v test_narrative` to check the original, reversed and flat scenarios.

## Important limitation

This data is synthetic. The findings demonstrate analysis and artifact
workflows; they do not describe a real product or company.

## Compare two synthetic runs

Run `python compare_fixture.py` and open `.comparison/index.html` locally.
The view compares the bundled original fixture to a one-cell edit: Paid Search
activations go from 210 to 500 in the final week, with signups unchanged.
Two disposable executions of the same builder supply the figures and links
to the original report JSON. Rate changes use percentage points; revenue
change uses percent. A reversal in activation is not a spending recommendation.

This optional example only accepts the original bundled synthetic CSV.
It does not change the source CSV, notebook, or canonical artifacts. The
generated view and reports are ignored by Git. Run
`python -m unittest -v` to verify both the existing outputs and the comparison.
