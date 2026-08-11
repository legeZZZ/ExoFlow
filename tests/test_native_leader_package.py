import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_state_machine():
    path = ROOT / "packages" / "team-leader" / "scripts" / "state_machine.py"
    spec = importlib.util.spec_from_file_location("native_leader_state_machine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeLeaderPackageTests(unittest.TestCase):
    def test_state_machine_has_cas_and_approval_binding(self):
        machine = load_state_machine()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared" / "tasks" / "T1" / "state.json"
            machine.init_state(path, "T1", "trace-1", "software-engineering")
            machine.transition(path, "FUSED", "codeops-intake", "duplicate reports", 0)
            with self.assertRaises(machine.StateMachineError):
                machine.transition(path, "TRIAGED", "codeops-triage", "stale writer", 0)
            machine.transition(path, "TRIAGED", "codeops-triage", "risk assessed", 1)
            approval = machine.request_approval(
                path,
                "codeops-plan",
                {"files": ["src/retry_guard.py"], "commands": ["pytest"]},
                "TRIAGED",
            )
            self.assertEqual(approval["requested_state_version"], 2)
            machine.approve(
                path,
                approval["approval_id"],
                "codeops-reviewer",
                "APPROVED",
                approval["scope_digest"],
                "$matrix-event-1",
                "!codeops-room:local",
            )
            state = machine.load(path)
            self.assertEqual(state["approvals"][0]["status"], "APPROVED")
            self.assertEqual(state["approvals"][0]["decision_evidence"]["event_id"], "$matrix-event-1")
            self.assertEqual(len(state["events"]), 5)

    def test_package_contains_runtime_state_machine(self):
        builder_path = ROOT / "deploy" / "agentteams" / "build_packages.py"
        spec = importlib.util.spec_from_file_location("codeops_build_packages", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as directory:
            result = builder.build_packages(ROOT, Path(directory), "test-model")
            leader = next(item for item in result["packages"] if item["name"] == "codeops-lead")
            with ZipFile(leader["path"]) as archive:
                self.assertIn("skills/codeops-orchestration/scripts/state_machine.py", archive.namelist())


if __name__ == "__main__":
    unittest.main()
