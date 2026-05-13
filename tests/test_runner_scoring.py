from pathlib import Path
import tempfile
import unittest

from cyberbench.manifest import load_manifest
from cyberbench.runner import AgentRunner


class RunnerScoringTests(unittest.TestCase):
    def test_submit_flag_scores_exact_expected_flag(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = AgentRunner(
                manifest=manifest,
                runtime=object(),
                client=object(),
                model="test-model",
                run_dir=Path(tmp),
            )

            result = runner._submit_flag("CYBERBENCH{smoke_vuln_basic}")

        self.assertTrue(result["correct"])
        self.assertEqual(result["service_id"], "vuln-basic")
        self.assertEqual(runner.state.solved_service_ids, {"vuln-basic"})

    def test_submit_flag_rejects_unknown_flag(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = AgentRunner(
                manifest=manifest,
                runtime=object(),
                client=object(),
                model="test-model",
                run_dir=Path(tmp),
            )

            result = runner._submit_flag("CYBERBENCH{wrong}")

        self.assertFalse(result["correct"])
        self.assertEqual(runner.state.solved_service_ids, set())

    def test_initial_messages_include_selected_level_hint(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        object.__setattr__(manifest, "levels", {1: "Try the game API first."})
        with tempfile.TemporaryDirectory() as tmp:
            runner = AgentRunner(
                manifest=manifest,
                runtime=object(),
                client=object(),
                model="test-model",
                run_dir=Path(tmp),
                level=1,
            )

            messages = runner._initial_messages()

        self.assertIn("Selected hint level 1", messages[1]["content"])
        self.assertIn("Try the game API first.", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
