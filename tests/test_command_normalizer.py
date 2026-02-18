import unittest

from app.backend.command_normalizer import normalize_commands


class CommandNormalizerTests(unittest.TestCase):
    def test_repairs_set_global_param_bpm(self) -> None:
        normalized, notes = normalize_commands(
            [{"op": "set_global", "param": "bpm", "value": 110}]
        )
        self.assertEqual(normalized[0]["target"], "Clock.bpm")
        self.assertTrue(notes)

    def test_rebuilds_malformed_player_assign_flow(self) -> None:
        raw = [
            {"op": "player_assign", "player": "p1", "value": "pluck"},
            {"op": "player_set", "player": "p1", "param": "degree", "value": "[0,2,4,2]"},
            {"op": "player_set", "player": "p1", "param": "dur", "value": 0.25},
            {"op": "player_set", "player": "p1", "param": "oct", "value": 5},
        ]
        normalized, notes = normalize_commands(raw)

        assign = normalized[-1]
        self.assertEqual(assign["op"], "player_assign")
        self.assertEqual(assign["player"], "p1")
        self.assertEqual(assign["synth"], "pluck")
        self.assertEqual(assign["pattern"], "[0,2,4,2]")
        self.assertEqual(assign["kwargs"]["dur"], 0.25)
        self.assertEqual(assign["kwargs"]["oct"], 5)
        self.assertTrue(notes)

    def test_repair_cutoff_to_lpf(self) -> None:
        normalized, notes = normalize_commands(
            [{"op": "player_set", "player": "p1", "param": "cutoff", "value": 1500}]
        )
        self.assertEqual(normalized[0]["param"], "lpf")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
