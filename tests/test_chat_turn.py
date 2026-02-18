import tempfile
import unittest
from pathlib import Path

from app.backend.main import SessionState, chat_turn, state
from app.backend.store import Store
from app.shared.contracts import ChatTurnRequest


class _RuntimeStub:
    async def ensure_running(self) -> None:
        return None

    async def send_lines(self, source: str) -> None:
        self.last_source = source


class _LLMStub:
    async def generate_patch(self, prompt: str, intent: str, state: dict):
        return (
            [
                {"op": "set_global", "param": "bpm", "value": 96},
                {"op": "player_assign", "player": "p1", "value": "pluck"},
                {"op": "player_set", "player": "p1", "param": "degree", "value": "[0,2,4,2]"},
                {"op": "player_set", "player": "p1", "param": "dur", "value": 0.25},
            ],
            "stub-model",
        )


class _LLMFailingStub:
    async def generate_patch(self, prompt: str, intent: str, state: dict):
        raise RuntimeError("codex CLI binary not found: codex")


class ChatTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_model_commands_are_normalized_and_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_runtime = state.runtime
            old_llm = state.llm
            old_store = state.store
            old_session_id = state.current_session_id
            old_session_state = state.session_state

            try:
                state.runtime = _RuntimeStub()
                state.llm = _LLMStub()
                state.store = Store(Path(tmp) / "test.sqlite3")
                state.current_session_id = "test-session"
                state.store.ensure_session(state.current_session_id)
                state.session_state = SessionState()

                request = ChatTurnRequest(
                    session_id=state.current_session_id,
                    prompt="make it smoother",
                    intent="edit",
                )
                payload = await chat_turn(request)

                self.assertTrue(payload["normalized"])
                self.assertEqual(payload["apply_status"], "applied")
                self.assertTrue(payload["validation"]["valid"])
                self.assertGreater(len(payload["normalization_notes"]), 0)

                effective = payload["effective_commands"]
                self.assertEqual(effective[0]["target"], "Clock.bpm")
                self.assertEqual(effective[-1]["op"], "player_assign")
                self.assertEqual(effective[-1]["synth"], "pluck")
            finally:
                state.runtime = old_runtime
                state.llm = old_llm
                state.store = old_store
                state.current_session_id = old_session_id
                state.session_state = old_session_state

    async def test_llm_failure_returns_skipped_and_user_action_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_runtime = state.runtime
            old_llm = state.llm
            old_store = state.store
            old_session_id = state.current_session_id
            old_session_state = state.session_state

            try:
                state.runtime = _RuntimeStub()
                state.llm = _LLMFailingStub()
                state.store = Store(Path(tmp) / "test.sqlite3")
                state.current_session_id = "test-session"
                state.store.ensure_session(state.current_session_id)
                state.session_state = SessionState()

                request = ChatTurnRequest(
                    session_id=state.current_session_id,
                    prompt="make it filthy",
                    intent="edit",
                )
                payload = await chat_turn(request)

                self.assertEqual(payload["model"], "llm-failed")
                self.assertEqual(payload["apply_status"], "skipped")
                self.assertFalse(payload["validation"]["valid"])
                self.assertTrue(payload["normalized"])
                self.assertTrue(payload["needs_user_input"])
                self.assertTrue(any("LLM backend failed" in n for n in payload["normalization_notes"]))
            finally:
                state.runtime = old_runtime
                state.llm = old_llm
                state.store = old_store
                state.current_session_id = old_session_id
                state.session_state = old_session_state


if __name__ == "__main__":
    unittest.main()
