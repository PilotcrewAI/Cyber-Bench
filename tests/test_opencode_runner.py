from pathlib import Path
import tempfile
import unittest

from cyberbench.manifest import load_manifest
from cyberbench.opencode_runner import OpenCodeRunner, _opencode_model, _summarize_opencode_usage


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

        self.assertIn("http://target:8081/ (vuln-basic, scored CTF)", doc)
        self.assertIn("http://target:8082/ (decoy-status, decoy)", doc)
        self.assertNotIn("expected_flags", doc)

    def test_summarize_opencode_usage_reads_step_finish_events(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"text","part":{"text":"ignored"}}',
                (
                    '{"type":"step_finish","part":{"cost":0.25,'
                    '"tokens":{"input":1,"output":2,"reasoning":3,"cache":{"read":4,"write":5}}}}'
                ),
                (
                    '{"type":"step_finish","part":{"cost":0.75,'
                    '"tokens":{"input":10,"output":20,"reasoning":30,"cache":{"read":40,"write":50}}}}'
                ),
            ]
        )

        usage = _summarize_opencode_usage(stdout)

        self.assertEqual(usage["steps"], 2)
        self.assertEqual(usage["cost_usd"], 1.0)
        self.assertEqual(usage["tokens"]["input"], 11)
        self.assertEqual(usage["tokens"]["output"], 22)
        self.assertEqual(usage["tokens"]["reasoning"], 33)
        self.assertEqual(usage["tokens"]["cache"], {"read": 44, "write": 55})


if __name__ == "__main__":
    unittest.main()
