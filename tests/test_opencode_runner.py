import json
from pathlib import Path
import tempfile
import unittest

from cyberbench.manifest import load_manifest
from cyberbench.opencode_runner import OpenCodeRunner, _opencode_model


class DummyRuntime:
    compose_path = Path("/tmp/cyberbench-compose.yml")
    project = "cyberbench_test"


class OpenCodeRunnerTests(unittest.TestCase):
    def test_opencode_model_uses_openrouter_provider_prefix(self) -> None:
        self.assertEqual(_opencode_model("anthropic/claude-haiku-4.5"), "openrouter/anthropic/claude-haiku-4.5")
        self.assertEqual(_opencode_model("openrouter/openai/gpt-5.4-nano"), "openrouter/openai/gpt-5.4-nano")

    def test_targets_doc_comes_from_manifest_target_ports(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
            )

            doc = runner._targets_doc()

        self.assertIn("target-1: http://target:8081/", doc)
        self.assertIn("target-2: http://target:8082/", doc)
        self.assertNotIn("vuln-basic", doc)
        self.assertNotIn("decoy-status", doc)
        self.assertNotIn("scored CTF", doc)
        self.assertNotIn("decoy", doc)
        self.assertNotIn("expected_flags", doc)

    def test_targets_doc_includes_selected_level_hint(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        object.__setattr__(manifest, "levels", {2: "Inspect the JSON API routes."})
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
                level=2,
            )

            doc = runner._targets_doc()

        self.assertIn("Selected Hint Level 2", doc)
        self.assertIn("Inspect the JSON API routes.", doc)

    def test_opencode_cost_warning_records_each_threshold_once(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
            )

            runner._warn_for_opencode_usage({"cost_usd": 0.96})
            runner._warn_for_opencode_usage({"cost_usd": 0.96})

            events = [
                json.loads(line)
                for line in runner.transcript_path.read_text().splitlines()
                if json.loads(line)["event"] == "cost_warning"
            ]

        self.assertEqual([event["threshold_percent"] for event in events], [50, 80, 95])

    def test_opencode_cost_budget_exhaustion_uses_standard_status(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
            )

            self.assertFalse(runner._opencode_budget_exhausted({"cost_usd": 0.99}))
            self.assertTrue(runner._opencode_budget_exhausted({"cost_usd": 1.0}))
            result = runner._result(
                {
                    "returncode": -15,
                    "budget_exhausted": True,
                    "usage": {"cost_usd": 1.0, "steps": 3},
                    "stdout_path": "stdout.jsonl",
                    "stderr_path": "stderr.log",
                }
            )

        self.assertTrue(result["opencode_budget_exhausted"])


if __name__ == "__main__":
    unittest.main()
