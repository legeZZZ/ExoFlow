import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).parents[1]


def load_builder():
    path = ROOT / "deploy" / "agentteams" / "build_packages.py"
    spec = importlib.util.spec_from_file_location("codeops_build_packages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentTeamsPackageTests(unittest.TestCase):
    def test_version_matrix_pins_beta_api_contract(self):
        matrix = json.loads((ROOT / "deploy" / "agentteams" / "compatibility.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["selected_release"], "v1.2.0-beta.1")
        self.assertEqual(matrix["selected_api_version"], "agentteams.io/v1beta1")
        stable = next(item for item in matrix["candidates"] if item["release"] == "v1.1.2")
        self.assertFalse(stable["compatible_with_codeops_setup"])

    def test_resource_manifest_has_nine_workers_and_no_local_package_uri(self):
        manifest = (ROOT / "deploy" / "agentteams" / "codeops-setup.yaml").read_text(encoding="utf-8")
        team_manifest = (ROOT / "deploy" / "agentteams" / "codeops-team.yaml").read_text(encoding="utf-8")
        self.assertEqual(manifest.count("kind: Worker\n"), 9)
        self.assertIn("kind: Manager\nmetadata:\n  name: default\n", manifest)
        self.assertIn("goai.codeops/agentteams-release: v1.2.0-beta.1", manifest)
        self.assertNotIn("package: file://", manifest)
        self.assertLess(team_manifest.index("kind: Team\n"), team_manifest.index("kind: Human\n"))
        self.assertIn("  leader:\n    name: codeops-lead\n", team_manifest)
        self.assertEqual(team_manifest.count("role: team_leader"), 1)
        self.assertEqual(team_manifest.count("role: worker"), 8)
        worker_documents = [document for document in manifest.split("\n---\n") if "kind: Worker\n" in document]
        self.assertEqual(len(worker_documents), 9)
        for document in worker_documents:
            self.assertIn("    - mcporter\n", document)
            self.assertIn("  mcpServers:\n    - name: codeops-state\n", document)
            self.assertIn("      url: __CODEOPS_STATE_MCP_URL__\n", document)

    def test_skill_matrix_is_twelve_capabilities_and_many_to_many(self):
        matrix = json.loads((ROOT / "packages" / "skill-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(len(matrix["skills"]), 12)
        self.assertEqual(len(matrix["agents"]), 9)
        uses = {skill: 0 for skill in matrix["skills"]}
        for skills in matrix["agents"].values():
            for skill in skills:
                uses[skill] += 1
        self.assertTrue(all(count >= 1 for count in uses.values()))
        self.assertGreater(sum(count > 1 for count in uses.values()), 1)

    def test_worker_packages_are_deterministic_and_officially_shaped(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            result_a = builder.build_packages(ROOT, Path(first), "test-model")
            result_b = builder.build_packages(ROOT, Path(second), "test-model")
            digests_a = {item["name"]: item["sha256"] for item in result_a["packages"]}
            digests_b = {item["name"]: item["sha256"] for item in result_b["packages"]}
            self.assertEqual(len(digests_a), 9)
            self.assertEqual(digests_a, digests_b)
            capability_names = {
                name
                for item in result_a["packages"]
                for name in item["skills"]
                if name in {
                    "issue-fusion", "repo-map", "root-cause-probe", "runbook-rag",
                    "incident-memory", "skill-distiller", "risk-guard", "policy-check",
                    "judge-calibrator", "safe-patch-exec", "verify-and-replay", "resume-guard",
                }
            }
            self.assertEqual(len(capability_names), 12)
            executor = next(item for item in result_a["packages"] if item["name"] == "codeops-executor")
            self.assertEqual(executor["runtime"], "hermes")
            with ZipFile(executor["path"]) as archive:
                names = archive.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("skills/approved-patch-execution/SKILL.md", names)
                self.assertIn("skills/safe-patch-exec/skill.yaml", names)
                self.assertIn("skills/resume-guard/evals/cases.json", names)
                self.assertEqual(len(names), len(set(names)))
                package_manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(package_manifest["type"], "worker")
                self.assertEqual(package_manifest["version"], 1)
                self.assertEqual(package_manifest["worker"]["runtime"], "hermes")
                self.assertEqual(package_manifest["worker"]["model"], "test-model")

    def test_apply_script_uses_beta_controller_cli_only(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            command_log = temporary / "docker.log"
            rendered_manifest = temporary / "rendered.yaml"
            identity_file = temporary / "worker-identities.json"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n"
                "if [ \"$1\" = version ]; then echo 29.6.2; fi\n"
                "if [ \"$1\" = inspect ]; then echo true; fi\n"
                "if [ \"$1\" = cp ] && [ \"$3\" = agentteams-controller:/tmp/codeops-setup.yaml ]; then cp \"$2\" \"$FAKE_RENDERED_MANIFEST\"; fi\n"
                "if [ \"$1\" = exec ] && [ \"$3\" = cat ]; then worker=$(basename \"$4\" .env); printf 'WORKER_GATEWAY_KEY=\\\"token-%s\\\"\\n' \"$worker\"; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            hermes_config = temporary / "hermes.yaml"
            hermes_config.write_text("model:\n  default: test-model\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PATH": str(fake_bin) + os.pathsep + env["PATH"],
                    "FAKE_DOCKER_LOG": str(command_log),
                    "FAKE_RENDERED_MANIFEST": str(rendered_manifest),
                    "CODEOPS_MODEL": "test-model",
                    "CODEOPS_PACKAGE_OUTPUT": str(temporary / "packages"),
                    "CODEOPS_STATE_MCP_URL": "http://host.docker.internal:8780/mcp",
                    "CODEOPS_IDENTITY_FILE": str(identity_file),
                }
            )
            result = subprocess.run(
                ["bash", str(ROOT / "deploy" / "agentteams" / "apply_codeops.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = command_log.read_text(encoding="utf-8")
            self.assertNotIn("hiclaw-manager", commands)
            self.assertIn("exec agentteams-controller hiclaw apply -f /tmp/codeops-setup.yaml", commands)
            self.assertEqual(commands.count("hiclaw apply worker --name"), 9)
            self.assertIn("hiclaw get managers default", commands)
            self.assertIn("hiclaw apply -f /tmp/codeops-team.yaml", commands)
            self.assertLess(commands.rindex("hiclaw apply worker --name"), commands.index("hiclaw apply -f /tmp/codeops-team.yaml"))
            rendered = rendered_manifest.read_text(encoding="utf-8")
            self.assertEqual(rendered.count("http://host.docker.internal:8780/mcp"), 9)
            self.assertNotIn("__CODEOPS_STATE_MCP_URL__", rendered)
            identities = json.loads(identity_file.read_text(encoding="utf-8"))
            self.assertEqual(len(identities), 9)
            self.assertEqual(identities["token-codeops-executor"], "codeops-executor")
            self.assertEqual(identity_file.stat().st_mode & 0o777, 0o600)
            combined_output = result.stdout + result.stderr
            self.assertNotIn("token-codeops-", combined_output)


if __name__ == "__main__":
    unittest.main()
