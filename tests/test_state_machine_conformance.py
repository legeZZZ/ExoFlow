"""Pin every state-machine consumer to the single source of truth.

state_machine_def.py is authoritative. The Worker-package oracle
(packages/team-leader/scripts/state_machine.py) ships inside a ZIP and cannot
import the package, so it embeds a copy; this test makes drift a build
failure instead of a runtime surprise.
"""

import importlib.util
import unittest
from pathlib import Path

from exoflow import state_machine_def
from exoflow.foundation import AgentTeamsControlPlane


ROOT = Path(__file__).parents[1]


def load_worker_state_machine():
    path = ROOT / "packages" / "team-leader" / "scripts" / "state_machine.py"
    spec = importlib.util.spec_from_file_location("conformance_state_machine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def as_plain_sets(table):
    return {state: set(targets) for state, targets in table.items()}


class StateMachineConformanceTests(unittest.TestCase):
    def test_worker_package_matches_shared_definition(self):
        machine = load_worker_state_machine()
        self.assertEqual(as_plain_sets(machine.TRANSITIONS), as_plain_sets(state_machine_def.TRANSITIONS))
        self.assertEqual(as_plain_sets(machine.ACTOR_TARGETS), as_plain_sets(state_machine_def.ACTOR_TARGETS))

    def test_foundation_control_plane_uses_shared_definition(self):
        self.assertEqual(
            as_plain_sets(AgentTeamsControlPlane.TRANSITIONS),
            as_plain_sets(state_machine_def.TRANSITIONS),
        )

    def test_readonly_branch_is_wired(self):
        self.assertIn("READONLY_VERIFYING", state_machine_def.TRANSITIONS["LOCATED"])
        self.assertEqual(state_machine_def.TRANSITIONS["READONLY_VERIFYING"], {"READONLY_VERIFIED", "NEEDS_HUMAN", "RECOVERING"})
        self.assertEqual(state_machine_def.TRANSITIONS["READONLY_VERIFIED"], {"EVIDENCE_PACKED", "NEEDS_HUMAN", "RECOVERING"})
        self.assertEqual(state_machine_def.TRANSITIONS["EVIDENCE_PACKED"], {"CLOSED"})

    def test_leader_cannot_own_domain_stage_states(self):
        lead_targets = state_machine_def.ACTOR_TARGETS["codeops-lead"]
        domain_states = {"FUSED", "TRIAGED", "BOOTSTRAPPED", "LOCATED", "PLANNED", "PATCHED", "VERIFYING", "RELEASE_READY", "READONLY_VERIFYING", "READONLY_VERIFIED"}
        self.assertTrue(domain_states.isdisjoint(lead_targets))

    def test_verification_gates_require_current_version_report(self):
        self.assertEqual(
            state_machine_def.TRANSITION_REQUIRED_ARTIFACTS[("VERIFYING", "RELEASE_READY")],
            ("VerificationReport", True),
        )
        self.assertEqual(
            state_machine_def.TRANSITION_REQUIRED_ARTIFACTS[("READONLY_VERIFYING", "READONLY_VERIFIED")],
            ("VerificationReport", True),
        )


if __name__ == "__main__":
    unittest.main()
