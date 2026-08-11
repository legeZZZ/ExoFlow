import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from goai_control_tower.cli import main
from goai_control_tower.configuration import load_config


class PackageEntrypointTests(unittest.TestCase):
    def test_packaged_config_and_sample_input_run_track1(self):
        config = load_config()
        self.assertEqual(config["runtime"]["track1_provider"], "fixture-local")
        sample = Path(__file__).parents[1] / "samples" / "track1" / "input.json"
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with redirect_stdout(output):
                status = main(["--track", "track1", "--output", directory, "--track1-input", str(sample)])
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["track1"]["state"], "CLOSED")
            self.assertEqual(result["track1"]["hidden_verification"], "pass")
            self.assertTrue((Path(directory) / "evidence" / "T1-codeops-demo.json").is_file())
