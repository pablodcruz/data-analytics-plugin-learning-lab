"""Run the real builder in a fresh directory; never modify a learner's fixture."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class NarrativeTests(unittest.TestCase):
    def rebuild(self, edit=lambda rows: None, error=None):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            shutil.copyfile(ROOT / "build_lab.py", dest / "build_lab.py")
            with (ROOT / "sample-product-growth.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            edit(rows)
            with (dest / "sample-product-growth.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            run = subprocess.run([sys.executable, "build_lab.py"], cwd=dest, capture_output=True, text=True)
            if error:
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(error, run.stderr)
                self.assertFalse((dest / "artifact.json").exists())
                return
            self.assertEqual(run.returncode, 0, run.stderr)
            def read(name):
                return json.loads((dest / name).read_text(encoding="utf-8"))
            nb = read("product-growth-analysis.ipynb")
            artifact = read("artifact.json")
            results = read("analysis-results.json")
            self.assertEqual(results["channel_summary"], artifact["snapshot"]["datasets"]["channel_summary"])
            for cell in nb["cells"]:
                if cell["cell_type"] == "code":
                    self.assertIsNotNone(cell["execution_count"])
                    self.assertFalse(any(o["output_type"] == "error" for o in cell["outputs"]))
            notebook = "".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
            report = "\n".join(b.get("body", "") for b in artifact["manifest"]["blocks"])
            for phrase in ("Scale the winners", "Paid Search is the clear drag", "Partners and Referral lead quality"):
                self.assertNotIn(phrase, str(artifact["manifest"]) + notebook)
            return notebook, report, artifact

    def test_original_decline(self):
        nb, report, _ = self.rebuild()
        for text in (nb, report):
            self.assertIn("Paid Search activation fell 17.3 percentage points", text)
            self.assertIn("Overall activation fell 3.7 percentage points", text)
            self.assertIn("Inspect the activation declines in Paid Search", text)

    def test_flip_one_cell_changes_both_outputs_and_followup(self):
        def edit(rows):
            next(r for r in rows if r["week_start"] == "2026-05-25"
                 and r["acquisition_channel"] == "Paid Search")["activated_users"] = "500"
        nb, report, artifact = self.rebuild(edit)
        for text in (nb, report):
            self.assertIn("Paid Search activation rose 37.4 percentage points", text)
            self.assertIn("No channel has a first-to-last activation decline", text)
            self.assertLess(text.index("Paid Search activation"), text.index("Partners activation"))
        self.assertIn("Overall activation rose", artifact["manifest"]["charts"][0]["subtitle"])

    def test_flat(self):
        def edit(rows):
            first = {r["acquisition_channel"]: r for r in rows if r["week_start"] == "2026-04-06"}
            for r in rows:
                if r["week_start"] == "2026-05-25":
                    r.update({k: v for k, v in first[r["acquisition_channel"]].items() if k != "week_start"})
        nb, report, _ = self.rebuild(edit)
        for text in (nb, report):
            self.assertIn("Paid Search activation was unchanged at display precision", text)
            self.assertIn("Overall activation was unchanged at display precision", text)
            self.assertIn("No channel has a first-to-last activation decline", text)

    def test_new_channel_and_zero_revenue_baseline(self):
        def edit(rows):
            for r in rows:
                if r["acquisition_channel"] == "Paid Search":
                    r["acquisition_channel"] = "Newsletter"
                if r["week_start"] == "2026-04-06":
                    r["revenue_usd"] = "0"
                    r["support_tickets"] = "0"
        nb, report, artifact = self.rebuild(edit)
        for text in (nb, report):
            self.assertNotIn("Paid Search", text)
            self.assertIn("Newsletter activation fell 17.3 percentage points", text)
            self.assertIn("revenue has no percentage comparison", text)
        headline = artifact["snapshot"]["datasets"]["headline_metrics"][0]
        self.assertIsNone(headline["revenue_growth"])
        self.assertIsNone(headline["ticket_intensity_growth"])

    def test_reject_duplicate_grain_even_if_counts_are_unchanged(self):
        self.rebuild(lambda rows: rows[-1].update(rows[-2]), error="one row per channel per week")

    def test_reject_undefined_activation(self):
        self.rebuild(lambda rows: rows[-1].update(signups="0"), error="positive signups")


if __name__ == "__main__":
    unittest.main()
