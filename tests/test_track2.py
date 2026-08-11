import tempfile
import unittest
from pathlib import Path

from goai_control_tower.track2 import public_case, run_case


class Track2Tests(unittest.TestCase):
    def test_case_a_is_descriptive_only(self):
        with tempfile.TemporaryDirectory() as directory:
            result = public_case(run_case(Path(directory), "A"))
            self.assertEqual(result["summary"]["final_state"], "CLOSED")
            self.assertEqual(result["summary"]["causal_outcome"], "DESCRIPTIVE_ONLY")
            self.assertEqual(result["claim"]["claim_type"], "descriptive_only")
            self.assertNotIn("truth", result)

    def test_case_b_fails_closed_with_data_path(self):
        with tempfile.TemporaryDirectory() as directory:
            result = public_case(run_case(Path(directory), "B"))
            self.assertEqual(result["summary"]["causal_outcome"], "DATA_INSUFFICIENT")
            quality_reports = [artifact for artifact in result["artifacts"] if artifact["artifact_type"] == "DataQualityReport"]
            self.assertIn("activity_config", quality_reports[0]["payload"]["missing_fields"])
            self.assertEqual(result["summary"]["final_state"], "CLOSED")

    def test_case_c_has_randomized_effect_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_case(Path(directory), "C")
            self.assertEqual(result["summary"]["causal_outcome"], "CAUSAL_READY")
            self.assertEqual(result["claim"]["claim_type"], "causal_effect")
            self.assertIn("estimate", result["estimate"]["issued"])
            self.assertEqual(result["causal_readiness"]["estimand"], "ITT on issued and net_premium")
