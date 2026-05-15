import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from cyberbench.manifest import load_manifest
from cyberbench.opencode_runner import (
    OpenCodeRunner,
    _opencode_error_from_line,
    _opencode_model,
    _add_opencode_step_usage,
    _default_opencode_workspace,
    _summarize_opencode_session,
    _sum_opencode_session_cost_usd,
)


class DummyRuntime:
    compose_path = Path("/tmp/cyberbench-compose.yml")
    project = "cyberbench_test"


class OpenCodeRunnerTests(unittest.TestCase):
    def test_opencode_model_uses_openrouter_provider_prefix(self) -> None:
        self.assertEqual(_opencode_model("anthropic/claude-haiku-4.5"), "openrouter/anthropic/claude-haiku-4.5")
        self.assertEqual(_opencode_model("openrouter/openai/gpt-5.4-nano"), "openrouter/openai/gpt-5.4-nano")

    def test_sum_opencode_session_cost_usd_matches_workspace_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            workspace = Path(tmp) / "cyberbench-opencode" / "run-abc123" / "workspace"
            workspace.mkdir(parents=True)
            resolved = str(workspace.resolve())
            token = workspace.resolve().parent.name
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE session (directory TEXT, path TEXT, cost REAL NOT NULL DEFAULT 0)"
            )
            conn.execute(
                "INSERT INTO session (directory, path, cost) VALUES (?, '', 1.25)",
                (resolved,),
            )
            conn.execute(
                "INSERT INTO session (directory, path, cost) VALUES ('', ?, 2.5)",
                (f"partial/{token}/workspace",),
            )
            conn.execute(
                "INSERT INTO session (directory, path, cost) VALUES ('', 'unrelated/other', 99.0)",
            )
            conn.commit()
            conn.close()

            total = _sum_opencode_session_cost_usd(db_path, workspace)

        self.assertEqual(total, 3.75)

    def test_default_workspace_is_outside_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "smoke-web" / "run"

            workspace = _default_opencode_workspace(run_dir)

        self.assertNotEqual(workspace, run_dir / "workspace")
        self.assertIn("cyberbench-opencode", workspace.parts)
        self.assertEqual(workspace.name, "workspace")

    def test_prepare_workspace_disables_project_config_and_host_bash(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "exec-workspace"
            runner = OpenCodeRunner(
                manifest=manifest,
                runtime=DummyRuntime(),
                model="test/model",
                run_dir=Path(tmp) / "run",
                openrouter_api_key="test-key",
                workspace=workspace,
            )

            runner._prepare_workspace()
            env = runner._opencode_env()

            config = json.loads((workspace / ".opencode" / "opencode.json").read_text(encoding="utf-8"))
            agent = (workspace / ".opencode" / "agent" / "cyberbench.md").read_text(encoding="utf-8")
            plugin = (workspace / ".opencode" / "plugins" / "cyberbench-shell-guard.js").read_text(
                encoding="utf-8"
            )
            self.assertEqual(config["share"], "disabled")
            self.assertEqual(config["permission"]["external_directory"], "deny")
            self.assertEqual(env["HOME"], str(runner.opencode_home))
            self.assertEqual(env["XDG_DATA_HOME"], str(runner.opencode_data_dir))
            self.assertEqual(env["OPENCODE_CONFIG"], str(workspace / ".opencode" / "opencode.json"))
            self.assertEqual(env["OPENCODE_CONFIG_DIR"], str(workspace / ".opencode"))
            self.assertEqual(env["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
            self.assertEqual(env["OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"], "1")
            self.assertIn('    "*": deny', agent)
            self.assertIn('    "./bench_shell *": allow', agent)
            self.assertIn('    "./submit_flag *": allow', agent)
            self.assertIn("  external_directory: deny", agent)
            self.assertNotIn("  bash: allow", agent)
            self.assertIn('"tool.execute.before"', plugin)
            self.assertIn("function isQuotedHelperInvocation(command)", plugin)
            self.assertIn("isQuotedHelperInvocation(command)", plugin)
            self.assertIn("./bench_shell '<command>'", plugin)
            self.assertIn("./submit_flag '<flag>'", plugin)

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

    def test_session_summary_extracts_usage_and_length_stop(self) -> None:
        session = {
            "cost": 0.33,
            "tokens_input": 1000,
            "tokens_output": 200,
            "tokens_reasoning": 300,
            "tokens_cache_read": 400,
            "tokens_cache_write": 0,
        }
        parts = [
            {
                "data": {
                    "type": "step-finish",
                    "cost": 0.1,
                    "reason": "tool-calls",
                    "tokens": {
                        "input": 10,
                        "output": 20,
                        "reasoning": 30,
                        "cache": {"read": 40, "write": 5},
                    },
                }
            },
            {
                "data": {
                    "type": "step-finish",
                    "cost": 0.23,
                    "reason": "length",
                    "tokens": {
                        "input": 11,
                        "output": 21,
                        "reasoning": 31,
                        "cache": {"read": 41, "write": 6},
                    },
                }
            },
        ]

        summary = _summarize_opencode_session(session, parts)

        self.assertEqual(summary["stop_reason"], "length")
        self.assertEqual(summary["usage"]["steps"], 2)
        self.assertEqual(summary["usage"]["cost_usd"], 0.33)
        self.assertEqual(summary["usage"]["tokens"]["input"], 21)
        self.assertEqual(summary["usage"]["tokens"]["output"], 41)
        self.assertEqual(summary["usage"]["tokens"]["reasoning"], 61)
        self.assertEqual(summary["usage"]["tokens"]["cache"]["read"], 81)
        self.assertEqual(summary["usage"]["tokens"]["cache"]["write"], 11)

    def test_opencode_step_usage_accepts_session_event_shape(self) -> None:
        usage = {
            "steps": 0,
            "cost_usd": 0.0,
            "tokens": {
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        }
        line = json.dumps(
            {
                "type": "part",
                "data": {
                    "type": "step-finish",
                    "cost": 0.25,
                    "tokens": {
                        "input": 10,
                        "output": 20,
                        "reasoning": 30,
                        "cache": {"read": 40, "write": 5},
                    },
                },
            }
        )

        self.assertTrue(_add_opencode_step_usage(usage, line))

        self.assertEqual(usage["steps"], 1)
        self.assertEqual(usage["cost_usd"], 0.25)
        self.assertEqual(usage["tokens"]["input"], 10)
        self.assertEqual(usage["tokens"]["cache"]["read"], 40)

    def test_status_marks_opencode_length_stop(self) -> None:
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
                "usage": {"cost_usd": 0.57, "steps": 33},
                "opencode_stop_reason": "length",
            }
            runner._set_final_status(completed)

            result = runner._result(completed)

        self.assertEqual(result["status"], "opencode_length_stop")
        self.assertEqual(result["opencode_stop_reason"], "length")
        self.assertIn("length limit", result["error"])

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
