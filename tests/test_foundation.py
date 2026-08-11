import tempfile
import unittest
from pathlib import Path

from goai_control_tower.foundation import AgentIdentity, AgentTeamsControlPlane, ApprovalError, ConcurrentStateError, PORT_MANIFESTS, SQLiteCheckpointProvider, StateTransitionError


class FoundationTests(unittest.TestCase):
    def test_state_authority_and_invalid_transition(self):
        control_plane = AgentTeamsControlPlane()
        control_plane.register_agent(AgentIdentity("agent", "test", ["FUSED"], ["test"], [], []))
        task = control_plane.create_task("task-1", "test", {"value": 1})
        self.assertEqual(task.state, "RECEIVED")
        with self.assertRaises(StateTransitionError):
            control_plane.transition("task-1", "CLOSED", "test", "invalid")
        with self.assertRaises(PermissionError):
            control_plane.transition("task-1", "FUSED", "unknown", "unknown actor")
        control_plane.transition("task-1", "FUSED", "agent", "valid")
        self.assertEqual(control_plane.tasks["task-1"].state_version, 1)
        self.assertEqual(control_plane.trace("task-1")[-1]["event_type"], "STATE_TRANSITION")

    def test_transition_rejects_stale_state_version(self):
        control_plane = AgentTeamsControlPlane()
        control_plane.register_agent(AgentIdentity("agent", "test", ["FUSED"], ["test"], [], []))
        control_plane.create_task("task-cas", "test", {"value": 1})
        with self.assertRaises(ConcurrentStateError):
            control_plane.transition("task-cas", "FUSED", "agent", "stale writer", expected_state_version=1)
        control_plane.transition("task-cas", "FUSED", "agent", "current writer", expected_state_version=0)

    def test_approval_binds_state_scope_and_platform_evidence(self):
        control_plane = AgentTeamsControlPlane()
        control_plane.register_agent(AgentIdentity("plan", "test", ["FUSED"], ["test"], [], []))
        control_plane.create_task("task-approval", "test", {"value": 1})
        approval_id = control_plane.request_approval("task-approval", "plan", {"files": ["a.py"]}, expected_state="FUSED")
        control_plane.transition("task-approval", "FUSED", "plan", "approval gate", expected_state_version=0)
        scope_digest = control_plane.approvals[approval_id]["scope_digest"]
        with self.assertRaises(ApprovalError):
            control_plane.approve(approval_id, "reviewer", decision_evidence={"scope_digest": "wrong"})
        approval = control_plane.approve(approval_id, "reviewer", decision_evidence={
            "provider": "matrix",
            "reviewer_identity": "reviewer",
            "scope_digest": scope_digest,
            "room_id": "!room:example",
            "event_id": "$event",
        })
        self.assertEqual(approval["decision_evidence"]["room_id"], "!room:example")
        self.assertEqual(approval["decision_evidence"]["event_id"], "$event")

    def test_port_manifest_is_complete_and_unique(self):
        self.assertEqual(len(PORT_MANIFESTS), 15)
        self.assertEqual(len({item["port_id"] for item in PORT_MANIFESTS}), 15)
        self.assertTrue(all(item["contract"] for item in PORT_MANIFESTS))

    def test_topology_references_registered_agents(self):
        from goai_control_tower.track1 import build_control_plane
        control_plane = build_control_plane()
        topology = control_plane.topologies["codeops-control-tower"]
        self.assertEqual(topology.control_plane, "AgentTeamsControlPlane")
        self.assertTrue(any(edge["mode"] == "bounded-repair" for edge in topology.edges))
        self.assertIn("fan_out", topology.execution_semantics)

    def test_checkpoint_is_not_state_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = SQLiteCheckpointProvider(Path(directory) / "checkpoints.sqlite3")
            provider.save("task", 4, {"state": "VERIFYING"})
            loaded = provider.load("task")
            self.assertEqual(loaded["state_version"], 4)
            self.assertEqual(loaded["payload"]["state"], "VERIFYING")
