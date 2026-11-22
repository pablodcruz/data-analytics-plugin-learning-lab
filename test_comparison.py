import json
from pathlib import Path
import shutil
import tempfile
import unittest

from compare_fixture import ROOT, generate


class ComparisonTests(unittest.TestCase):
    def test_rebuilt_reports_match_readings_without_rewriting_lab(self):
        paths = ["sample-product-growth.csv", "analysis-results.json",
                 "product-growth-analysis.ipynb", "artifact.json"]
        before = [(ROOT / name).read_bytes() for name in paths]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / ".comparison"
            path = generate(ROOT, dest)
            html = path.read_bytes()
            for filename, delta, overall in (("original", -17.32, -3.68), ("edited", 37.4, 15.78)):
                rel = f"reports/{filename}-report.json"
                report = json.loads((dest / rel).read_bytes())
                ds = report["snapshot"]["datasets"]
                paid, = [m for m in ds["channel_summary"] if m["acquisition_channel"] == "Paid Search"]
                self.assertEqual(paid["activation_rate_change_pp"], delta)
                self.assertEqual(paid["revenue_growth"], -.1833)
                self.assertEqual(ds["headline_metrics"][0]["activation_rate_change_pp"], overall)
                self.assertIn(rel.encode(), html)
            for reading in ["−17.3", "+37.4", "−3.7 pp", "+15.8 pp", "−18.3%"]:
                self.assertIn(reading.encode(), html)
            # Percentages are the rates behind each bar, not additional changes.
            self.assertIn(b"Paid Search activation rates behind each bar", html)
            for date, rate, fraction, times in (
                ("Apr 6", "56.94%", "205 of 360 signups", 2),
                ("May 25", "39.62%", "210 of 530 signups", 1),
                ("May 25", "94.34%", "500 of 530 signups", 1),
            ):
                endpoint = (f'<dt>{date}</dt><dd><strong>{rate}</strong>'
                            f'<span class="rate-count">{fraction}</span></dd>')
                self.assertEqual(html.count(endpoint.encode()), times)
            self.assertEqual(html.count("−18.3%".encode()), 2)
            self.assertEqual(generate(ROOT, dest).read_bytes(), html)
        self.assertEqual([(ROOT / name).read_bytes() for name in paths], before)

    def test_rejects_changed_input_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = (ROOT / "sample-product-growth.csv").read_bytes()
            (root / "sample-product-growth.csv").write_bytes(fixture + b"\n")
            shutil.copyfile(ROOT / "build_lab.py", root / "build_lab.py")
            with self.assertRaisesRegex(ValueError, "original bundled synthetic CSV"):
                generate(root, root / ".comparison")
            self.assertFalse((root / ".comparison").exists())


if __name__ == "__main__":
    unittest.main()
