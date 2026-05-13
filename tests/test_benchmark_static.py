from pathlib import Path
import tempfile
import unittest

from cyberbench.benchmark_static import (
    build_openrouter_static,
    build_opencode_static,
    write_benchmark_static,
)
from cyberbench.manifest import load_manifest


class BenchmarkStaticTests(unittest.TestCase):
    def test_openrouter_payload_includes_system_user_and_tools(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "TASK"},
        ]
        tools = [{"type": "function", "function": {"name": "shell"}}]
        payload = build_openrouter_static(
            bundle_id=manifest.bundle_id,
            level=None,
            manifest_path=manifest.path,
            initial_messages=messages,
            tool_definitions=tools,
        )
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["backend"], "openrouter")
        titles = [section["title"] for section in payload["sections"]]
        self.assertIn("Bundle manifest path", titles)
        self.assertIn("System prompt (OpenRouter chat API)", titles)
        self.assertIn("Initial user message (targets & task)", titles)
        self.assertIn("Tool definitions (OpenRouter chat API)", titles)

    def test_opencode_round_trip_via_workspace_files(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            agent_dir = workspace / ".opencode" / "agent"
            agent_dir.mkdir(parents=True)
            (agent_dir / "cyberbench.md").write_text("AGENT\n", encoding="utf-8")
            (workspace / "TARGETS.md").write_text("# T\n", encoding="utf-8")
            payload = build_opencode_static(
                bundle_id=manifest.bundle_id,
                level=1,
                manifest_path=manifest.path,
                workspace=workspace,
                cli_prompt="CLI HERE",
            )
            write_benchmark_static(root, payload)
            written = (root / "benchmark_static.json").read_text(encoding="utf-8")
            self.assertIn("AGENT", written)
            self.assertIn("# T", written)
            self.assertIn("CLI HERE", written)
            self.assertEqual(payload["backend"], "opencode")
            self.assertEqual(payload["level"], 1)


if __name__ == "__main__":
    unittest.main()
