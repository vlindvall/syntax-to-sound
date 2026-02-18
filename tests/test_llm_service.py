import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from app.backend.llm_service import LLMService


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponsesAPI:
    def __init__(self, output_text: str, assert_schema: bool) -> None:
        self._output_text = output_text
        self._assert_schema = assert_schema

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        if self._assert_schema:
            text_format = kwargs["text"]["format"]
            assert text_format["type"] == "json_object"
        return _FakeResponse(self._output_text)


class _FakeAsyncOpenAI:
    def __init__(self, api_key: str, output_text: str, assert_schema: bool) -> None:
        self.api_key = api_key
        self.responses = _FakeResponsesAPI(output_text, assert_schema)


class LLMServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_key = os.environ.get("OPENAI_API_KEY")
        self._old_model = os.environ.get("OPENAI_MODEL")
        self._old_backend = os.environ.get("AI_DJ_LLM_BACKEND")

    def tearDown(self) -> None:
        if self._old_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._old_key

        if self._old_model is None:
            os.environ.pop("OPENAI_MODEL", None)
        else:
            os.environ["OPENAI_MODEL"] = self._old_model

        if self._old_backend is None:
            os.environ.pop("AI_DJ_LLM_BACKEND", None)
        else:
            os.environ["AI_DJ_LLM_BACKEND"] = self._old_backend

        sys.modules.pop("openai", None)

    def test_resolve_backend_chain_prefers_codex_before_openai(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"), patch(
            "app.backend.llm_service.os.access", return_value=True
        ):
            with patch.dict(
                "os.environ",
                {
                    "AI_DJ_LLM_BACKEND": "auto",
                    "OPENAI_API_KEY": "test-key",
                    "CODEX_CLI_COMMAND": "codex exec",
                },
                clear=True,
            ):
                service = LLMService()
                self.assertEqual(service._resolve_backend_chain(), ["codex-cli", "openai-api"])

    def test_resolve_backend_uses_codex_cli_when_available(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"), patch(
            "app.backend.llm_service.os.access", return_value=True
        ):
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
                self.assertEqual(service._resolve_backend_chain(), ["codex-cli"])

    def test_resolve_backend_finds_codex_in_common_paths_when_path_missing(self) -> None:
        def _which(name, path=None):  # type: ignore[no-untyped-def]
            if name != "codex":
                return None
            if path and "/opt/homebrew/bin" in path:
                return "/opt/homebrew/bin/codex"
            return None

        with patch("app.backend.llm_service.shutil.which", side_effect=_which), patch(
            "app.backend.llm_service.os.access", return_value=True
        ):
            with patch.dict(
                "os.environ",
                {
                    "AI_DJ_LLM_BACKEND": "auto",
                    "OPENAI_API_KEY": "",
                    "CODEX_CLI_COMMAND": "codex exec",
                    "PATH": "/usr/sbin:/sbin",
                },
                clear=True,
            ):
                service = LLMService()
                self.assertEqual(service.codex_command[0], "/opt/homebrew/bin/codex")
                self.assertEqual(service._resolve_backend_chain(), ["codex-cli"])

    def test_auto_falls_back_from_codex_to_openai(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"), patch(
            "app.backend.llm_service.os.access", return_value=True
        ):
            with patch.dict(
                "os.environ",
                {
                    "AI_DJ_LLM_BACKEND": "auto",
                    "OPENAI_API_KEY": "test-key",
                    "CODEX_CLI_COMMAND": "codex exec",
                },
                clear=True,
            ):
                service = LLMService()
                with patch.object(
                    service,
                    "_generate_codex_cli",
                    AsyncMock(side_effect=RuntimeError("codex unavailable")),
                ):
                    with patch.object(
                        service,
                        "_generate_openai",
                        AsyncMock(return_value=([{"op": "clock_clear"}], "gpt-5.2-codex")),
                    ):
                        commands, model = asyncio.run(service.generate_patch("stop", "edit"))
                        self.assertEqual(commands, [{"op": "clock_clear"}])
                        self.assertEqual(model, "gpt-5.2-codex")

    def test_uses_strict_json_schema_format(self) -> None:
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["OPENAI_MODEL"] = "gpt-5.2-codex"
        os.environ["AI_DJ_LLM_BACKEND"] = "openai-api"

        fake_mod = types.ModuleType("openai")
        fake_mod.AsyncOpenAI = lambda api_key: _FakeAsyncOpenAI(  # type: ignore[attr-defined]
            api_key,
            '{"commands":[{"op":"set_global","target":"Clock.bpm","value":120}]}',
            True,
        )
        sys.modules["openai"] = fake_mod

        service = LLMService()
        commands, model = asyncio.run(service.generate_patch("set bpm 120", "edit"))

        self.assertEqual(model, "gpt-5.2-codex")
        self.assertEqual(commands[0]["target"], "Clock.bpm")

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

    def test_invalid_model_payload_falls_back(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value=None):
            os.environ["OPENAI_API_KEY"] = "test-key"

            fake_mod = types.ModuleType("openai")
            fake_mod.AsyncOpenAI = lambda api_key: _FakeAsyncOpenAI(  # type: ignore[attr-defined]
                api_key,
                '{"foo":"bar"}',
                False,
            )
            sys.modules["openai"] = fake_mod

            service = LLMService()
            with self.assertRaisesRegex(RuntimeError, "all LLM backends failed"):
                asyncio.run(service.generate_patch("slow it down", "edit"))

    def test_generate_fallback_patch_supports_major_key(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value=None):
            os.environ.pop("OPENAI_API_KEY", None)
            service = LLMService()
            commands = service.generate_fallback_patch("make it major key", "edit")
            self.assertTrue(
                any(
                    cmd.get("op") == "set_global"
                    and cmd.get("target") == "Scale.default"
                    and cmd.get("value") == "major"
                    for cmd in commands
                )
            )

    def test_generate_fallback_patch_supports_drums(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value=None):
            os.environ.pop("OPENAI_API_KEY", None)
            service = LLMService()
            commands = service.generate_fallback_patch("add some drums", "edit")
            self.assertTrue(
                any(
                    cmd.get("op") == "player_assign"
                    and cmd.get("player") == "d1"
                    and cmd.get("synth") == "play"
                    for cmd in commands
                )
            )

    def test_generate_fallback_patch_supports_new_song_scene(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value=None):
            os.environ.pop("OPENAI_API_KEY", None)
            service = LLMService()
            commands = service.generate_fallback_patch("make a new song", "new_scene")
            self.assertEqual(commands[0]["op"], "clock_clear")

    def test_generate_codex_cli_uses_cli_output(self) -> None:
        with patch("app.backend.llm_service.shutil.which", return_value="/usr/local/bin/codex"), patch(
            "app.backend.llm_service.os.access", return_value=True
        ):
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
                ) as create_proc:
                    commands, model = asyncio.run(service.generate_patch("stop", "edit"))
                    self.assertEqual(commands, [{"op": "clock_clear"}])
                    self.assertEqual(model, "codex-cli:gpt-5-codex")
                    args = create_proc.await_args.args
                    self.assertIn("--output-last-message", args)

    def test_extract_commands_ignores_non_command_json_before_valid_payload(self) -> None:
        service = LLMService()
        output = (
            'user {"intent":"edit","prompt":"stop","schema_hint":{"commands":[{"op":"player_set"}]}}\n'
            'assistant {"commands":[{"op":"clock_clear"}]}'
        )
        commands = service._extract_commands(output)
        self.assertEqual(commands, [{"op": "clock_clear"}])


if __name__ == "__main__":
    unittest.main()
