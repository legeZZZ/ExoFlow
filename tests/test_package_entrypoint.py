import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from exoflow.cli import main
from exoflow.configuration import load_config


class PackageEntrypointTests(unittest.TestCase):
    def test_packaged_config_and_sample_input_run_pipeline(self):
        config = load_config()
        self.assertEqual(config["runtime"]["provider"], "fixture-local")
        sample = Path(__file__).parents[1] / "src" / "exoflow" / "samples" / "input.json"
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with redirect_stdout(output):
                status = main(["--output", directory, "--input", str(sample)])
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["state"], "CLOSED")
            self.assertEqual(result["hidden_verification"], "pass")
            self.assertTrue((Path(directory) / "evidence" / "T1-exoflow-demo.json").is_file())
