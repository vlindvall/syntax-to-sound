import tempfile
import unittest
from pathlib import Path

from app.backend.main import SessionState, _compute_revert, _extract_song_session_state, state


class RuntimeStateTests(unittest.TestCase):
    def test_extract_song_session_state_parses_globals_and_players(self) -> None:
        song_source = """
Clock.bpm = 134
Scale.default = Scale.minor
Root.default = \"D\"
p1 >> pluck([0,2,4,7], dur=1/4, amp=0.8)
d1 >> play(\"x-o-\", dur=1/2)
""".strip()

        with tempfile.TemporaryDirectory() as tmp:
            song_path = Path(tmp) / "song.py"
            song_path.write_text(song_source, encoding="utf-8")

            globals_state, players_state = _extract_song_session_state(song_path)

        self.assertEqual(globals_state["Clock.bpm"], 134)
        self.assertEqual(globals_state["Scale.default"], "Scale.minor")
        self.assertEqual(globals_state["Root.default"], "D")

        self.assertIn("p1", players_state)
        self.assertEqual(players_state["p1"]["synth"], "pluck")
        self.assertEqual(players_state["p1"]["pattern"], "[0,2,4,7]")
        self.assertIn("dur", players_state["p1"]["kwargs"])

        self.assertIn("d1", players_state)
        self.assertEqual(players_state["d1"]["pattern"], '"x-o-"')

    def test_compute_revert_restores_player_on_stop(self) -> None:
        old_session_state = state.session_state
        try:
            state.session_state = SessionState(
                globals={"Clock.bpm": 120},
                players={
                    "p1": {
                        "synth": "pluck",
                        "pattern": "[0,2,4]",
                        "kwargs": {"dur": 0.25, "amp": 0.7},
                        "dur": 0.25,
                        "amp": 0.7,
                    }
                },
                clock_started_at=123.0,
            )

            revert = _compute_revert([{"op": "player_stop", "player": "p1"}])

            self.assertEqual(len(revert), 1)
            self.assertEqual(revert[0]["op"], "player_assign")
            self.assertEqual(revert[0]["player"], "p1")
            self.assertNotIn("p1", state.session_state.players)
        finally:
            state.session_state = old_session_state


if __name__ == "__main__":
    unittest.main()
