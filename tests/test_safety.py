import unittest

from app.backend.safety import emit_python, validate_and_emit, validate_emitted_python


class SafetyTests(unittest.TestCase):
    def test_validation_accepts_valid_commands(self) -> None:
        commands = [
            {"op": "set_global", "target": "Clock.bpm", "value": 120},
            {"op": "player_set", "player": "p1", "param": "amp", "value": 0.7},
            {"op": "player_set", "player": "p1", "param": "dur", "value": 0.25},
        ]
        validated, emitted, errors = validate_and_emit(commands)
        self.assertEqual(errors, [])
        self.assertEqual(len(validated), 3)
        self.assertIn("Clock.bpm = 120", emitted)
        self.assertIn("p1.dur = 0.25", emitted)

    def test_rejects_unsafe_player(self) -> None:
        _, _, errors = validate_and_emit(
            [{"op": "player_set", "player": "x1", "param": "amp", "value": 0.2}]
        )
        self.assertTrue(errors)

    def test_rejects_forbidden_ast(self) -> None:
        with self.assertRaises(Exception):
            validate_emitted_python("__import__('os').system('whoami')")

    def test_deterministic_emitter(self) -> None:
        commands = [
            {
                "op": "player_assign",
                "player": "p1",
                "synth": "pluck",
                "pattern": "[0,2,4,7]",
                "kwargs": {"amp": 0.7, "dur": 0.25},
            }
        ]
        one = emit_python(validate_and_emit(commands)[0])
        two = emit_python(validate_and_emit(commands)[0])
        self.assertEqual(one, two)

    def test_accepts_extended_player_params(self) -> None:
        commands = [
            {"op": "player_set", "player": "b1", "param": "detune", "value": 0.2},
        ]
        _, emitted, errors = validate_and_emit(commands)
        self.assertEqual(errors, [])
        self.assertIn("b1.detune = 0.2", emitted)


if __name__ == "__main__":
    unittest.main()
