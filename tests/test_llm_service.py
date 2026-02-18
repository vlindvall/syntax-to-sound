import unittest
from unittest.mock import AsyncMock, patch

from app.backend.llm_service import LLMService


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_backend_prefers_openai_key_in_auto_mode(self) -> None:
        with patch.dict(
            "os.environ",
            {"AI_DJ_LLM_BACKEND": "auto", "OPENAI_API_KEY": "test-key"},
            clear=True,
        ):
            service = LLMService()
            self.assertEqual(service._resolve_backend(), "openai-api")

    def test_resolve_backend_uses_codex_cli_when_available(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"):
            with patch.dict(
                "os.environ",
                {
                    "AI_DJ_LLM_BACKEND": "auto",
                    "OPENAI_API_KEY": "",
                    "CODEX_CLI_COMMAND": "codex exec",
                },
                clear=True,
            ):
                service = LLMService()
                self.assertEqual(service._resolve_backend(), "codex-cli")

    def test_extract_commands_from_json_object(self) -> None:
        service = LLMService()
        commands = service._extract_commands('{"commands":[{"op":"clock_clear"}]}')
        self.assertEqual(commands, [{"op": "clock_clear"}])

    def test_extract_commands_from_text_with_embedded_json(self) -> None:
        service = LLMService()
        commands = service._extract_commands('note: {"commands":[{"op":"clock_clear"}]}')
        self.assertEqual(commands, [{"op": "clock_clear"}])

    def test_normalizes_set_global_param_alias(self) -> None:
        service = LLMService()
        commands = service._extract_commands('{"commands":[{"op":"set_global","param":"bpm","value":150}]}')
        self.assertEqual(
            commands,
            [{"op": "set_global", "param": "bpm", "value": 150, "target": "Clock.bpm"}],
        )

    def test_normalizes_player_assign_call_pattern(self) -> None:
        service = LLMService()
        commands = service._extract_commands(
            '{"commands":[{"op":"player_assign","player":"p1","pattern":"pluck(\'tri\', dur=0.25)"}]}'
        )
        self.assertEqual(commands[0]["synth"], "pluck")
        self.assertEqual(commands[0]["pattern"], "'tri'")
        self.assertEqual(commands[0]["kwargs"]["dur"], 0.25)

    async def test_generate_codex_cli_uses_cli_output(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"):
            with patch.dict(
                "os.environ",
                {
                    "AI_DJ_LLM_BACKEND": "codex-cli",
                    "OPENAI_API_KEY": "",
                    "CODEX_CLI_COMMAND": "codex exec",
                    "CODEX_MODEL": "gpt-5-codex",
                },
                clear=True,
            ):
                service = LLMService()
                fake_process = AsyncMock()
                fake_process.communicate = AsyncMock(
                    return_value=(b'{"commands":[{"op":"clock_clear"}]}', b"")
                )
                fake_process.returncode = 0

                with patch(
                    "app.backend.llm_service.asyncio.create_subprocess_exec",
                    AsyncMock(return_value=fake_process),
                ):
                    commands, model = await service.generate_patch("stop", "edit")
                    self.assertEqual(commands, [{"op": "clock_clear"}])
                    self.assertEqual(model, "codex-cli:gpt-5-codex")


if __name__ == "__main__":
    unittest.main()
