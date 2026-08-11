import unittest

from goai_control_tower.track2 import case_experiment_metadata, default_metric_contract, generate_dataset
from goai_control_tower.track2_analysis import causal_readiness, extract_features, sanitize_rows
from goai_control_tower.track2_benchmark import run_hidden_benchmark


class Track2AnalysisTests(unittest.TestCase):
    def test_feature_extraction_removes_oracle_fields(self):
        private_rows, _ = generate_dataset("C", seed=91, n=500)
        rows = sanitize_rows(private_rows)
        features = extract_features(rows, default_metric_contract(), case_experiment_metadata("C"))
        self.assertFalse(any(key.startswith("_") for key in features["available_fields"]))
        self.assertEqual(features["row_count"], 500)
        self.assertEqual(features["data_quality"]["missing_row_fields"], [])

    def test_readiness_uses_metadata_not_case_label(self):
        private_rows, _ = generate_dataset("C", seed=92, n=1200)
        rows = sanitize_rows(private_rows)
        metadata = case_experiment_metadata("A")
        features = extract_features(rows, default_metric_contract(), metadata)
        readiness = causal_readiness(features, default_metric_contract(), metadata)
        self.assertEqual(readiness["outcome"], "DESCRIPTIVE_ONLY")
        self.assertFalse(readiness["diagnostics"]["design_checks"]["randomized_assignment"])

    def test_unverified_randomization_cannot_pass_design_gate(self):
        private_rows, _ = generate_dataset("C", seed=93, n=1200)
        rows = sanitize_rows(private_rows)
        metadata = case_experiment_metadata("C")
        metadata["assignment_verified"] = False
        features = extract_features(rows, default_metric_contract(), metadata)
        readiness = causal_readiness(features, default_metric_contract(), metadata)
        self.assertEqual(readiness["outcome"], "DESCRIPTIVE_ONLY")
        self.assertIn("CAUSAL_DESIGN_NOT_VERIFIED", readiness["reason_codes"])

    def test_small_randomized_sample_fails_power_screen(self):
        private_rows, _ = generate_dataset("C", seed=94, n=80)
        rows = sanitize_rows(private_rows)
        metadata = case_experiment_metadata("C")
        features = extract_features(rows, default_metric_contract(), metadata)
        readiness = causal_readiness(features, default_metric_contract(), metadata)
        self.assertEqual(readiness["outcome"], "DESCRIPTIVE_ONLY")
        self.assertFalse(readiness["diagnostics"]["power"]["passed"])

    def test_hidden_benchmark_runs_in_isolated_worker(self):
        report = run_hidden_benchmark(seeds=(101, 211), n=1200)
        self.assertEqual(report["evaluated_cases"], 6)
        self.assertEqual(report["metrics"]["causal_gate_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["false_causal_assertion_rate"], 0.0)
        self.assertEqual(report["metrics"]["refusal_recall"], 1.0)
        self.assertEqual(report["worker_isolation"], "subprocess; public rows and metadata only")


if __name__ == "__main__":
    unittest.main()
