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
            [{"op": "player_set", "player": "_1", "param": "amp", "value": 0.2}]
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

    def test_accepts_dynamic_player_index(self) -> None:
        commands = [
            {"op": "player_set", "player": "p17", "param": "amp", "value": 0.4},
        ]
        _, emitted, errors = validate_and_emit(commands)
        self.assertEqual(errors, [])
        self.assertIn("p17.amp = 0.4", emitted)

    def test_accepts_dynamic_player_prefix(self) -> None:
        commands = [
            {"op": "player_set", "player": "h3", "param": "amp", "value": 0.3},
        ]
        _, emitted, errors = validate_and_emit(commands)
        self.assertEqual(errors, [])
        self.assertIn("h3.amp = 0.3", emitted)

    def test_rejects_zero_player_index(self) -> None:
        _, _, errors = validate_and_emit(
            [{"op": "player_set", "player": "p0", "param": "amp", "value": 0.2}]
        )
        self.assertTrue(errors)

    def test_accepts_negative_literal_assignments(self) -> None:
        validate_emitted_python("p1.pan = -0.5")

    def test_player_assign_pattern_plain_text_is_quoted(self) -> None:
        commands = [
            {
                "op": "player_assign",
                "player": "p1",
                "synth": "play",
                "pattern": "x-(-[--])o-",
                "kwargs": {},
            }
        ]
        _, emitted, errors = validate_and_emit(commands)
        self.assertEqual(errors, [])
        self.assertIn("p1 >> play('x-(-[--])o-')", emitted)


if __name__ == "__main__":
    unittest.main()
