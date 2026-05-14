import json
from pathlib import Path
import tempfile
import unittest

from cyberbench.manifest import load_manifest
from cyberbench.opencode_runner import OpenCodeRunner, _opencode_error_from_line, _opencode_model


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

        self.assertIn("## Hint:", doc)
        self.assertIn("Inspect the JSON API routes.", doc)

    def test_targets_doc_omits_hint_when_no_level_is_selected(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        object.__setattr__(manifest, "levels", {1: "Inspect the JSON API routes."})
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
            )

            doc = runner._targets_doc()

        self.assertNotIn("## Hint:", doc)
        self.assertNotIn("Inspect the JSON API routes.", doc)

    def test_targets_doc_includes_cumulative_level_hints(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        object.__setattr__(
            manifest,
            "levels",
            {
                1: "Start by mapping routes.",
                2: "Inspect the JSON API.",
                3: "Pollute the package lookup.",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
                level=3,
            )

            doc = runner._targets_doc()

        self.assertIn("## Hint:", doc)
        self.assertIn("Hint 1:\nStart by mapping routes.", doc)
        self.assertIn("Hint 2:\nInspect the JSON API.", doc)
        self.assertIn("Hint 3:\nPollute the package lookup.", doc)

    def test_opencode_error_line_extracts_provider_message(self) -> None:
        line = json.dumps(
            {
                "type": "error",
                "error": {
                    "name": "APIError",
                    "data": {
                        "message": (
                            "[Google] This model does not support assistant message prefill. "
                            "The conversation must end with a user message."
                        )
                    },
                },
            }
        )

        message = _opencode_error_from_line(line)

        self.assertIsNotNone(message)
        self.assertIn("APIError", message or "")
        self.assertIn("assistant message prefill", message or "")

    def test_status_marks_opencode_error_event_even_with_zero_returncode(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp),
                openrouter_api_key="test-key",
            )
            completed = {
                "event": "opencode_finish",
                "returncode": 0,
                "budget_exhausted": False,
                "stdout_path": "stdout.jsonl",
                "stderr_path": "stderr.log",
                "usage": {"cost_usd": 0.0, "steps": 0},
                "error": "APIError: assistant message prefill",
            }
            runner._set_final_status(completed)

            result = runner._result(completed)

        self.assertEqual(result["status"], "opencode_error")
        self.assertEqual(result["error"], "APIError: assistant message prefill")

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
