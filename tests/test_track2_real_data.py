import tempfile
import unittest
from pathlib import Path

from goai_control_tower.track2_real_data import analyze_bank_marketing_csv


CSV_FIXTURE = """age,job,marital,education,default,balance,housing,loan,contact,day_of_week,month,duration,campaign,pdays,previous,poutcome,y
58,management,married,tertiary,no,2143,yes,no,NaN,5,may,261,1,-1,0,NaN,no
42,technician,single,secondary,no,100,no,no,cellular,7,jun,420,2,18,1,success,yes
35,services,married,NaN,no,40,yes,no,telephone,9,jul,80,1,-1,0,NaN,no
"""


class Track2RealDataTests(unittest.TestCase):
    def test_real_adapter_profiles_rows_and_blocks_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bank.csv"
            path.write_text(CSV_FIXTURE, encoding="utf-8")
            result = analyze_bank_marketing_csv(path, max_rows=3)

        self.assertTrue(result["real_data"])
        self.assertEqual(result["profile"]["row_count"], 3)
        self.assertEqual(result["profile"]["subscriptions"], 1)
        self.assertEqual(result["profile"]["subscription_rate"], 0.333333)
        self.assertEqual(result["causal_readiness"]["outcome"], "DESCRIPTIVE_ONLY")
        self.assertIn("NO_TREATMENT_ASSIGNMENT", result["causal_readiness"]["reason_codes"])
        blocked = {item["field"] for item in result["feature_policy"]["blocked_features"]}
        self.assertEqual(blocked, {"duration", "y"})
        self.assertNotIn("duration", result["feature_policy"]["allowed_pre_call_features"])
        self.assertNotIn("sample", result)

    def test_real_adapter_emits_aggregate_evidence_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bank.csv"
            path.write_text(CSV_FIXTURE, encoding="utf-8")
            result = analyze_bank_marketing_csv(path, max_rows=2)

        self.assertEqual(len(result["evidence"]), 5)
        self.assertEqual(len(result["artifacts"]), 5)
        self.assertEqual(result["feature_policy"]["evidence_pack_policy"], "aggregate-only; no row samples or individual targeting lists")
        self.assertIn("不能声称因果", result["claim"]["statement"])


if __name__ == "__main__":
    unittest.main()
