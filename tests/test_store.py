import tempfile
import unittest
from pathlib import Path

from app.backend.store import Store


class StoreTests(unittest.TestCase):
    def test_store_crud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = Store(db_path)

            session_id = "session-1"
            store.ensure_session(session_id)
            turn_id = store.create_turn(session_id, "make it darker", "fallback-local", 123)
            patch_id = store.create_patch(
                turn_id,
                [{"op": "set_global", "target": "Clock.bpm", "value": 108}],
                [{"op": "set_global", "target": "Clock.bpm", "value": 108}],
                False,
                [],
                "Clock.bpm = 108",
                "valid",
                "applied",
                [{"op": "set_global", "target": "Clock.bpm", "value": 120}],
            )

            patch = store.get_patch(patch_id)
            self.assertIsNotNone(patch)
            assert patch is not None
            self.assertEqual(patch["apply_status"], "applied")

            last = store.get_last_applied_patch(session_id)
            self.assertIsNotNone(last)
            details = store.get_session(session_id)
            self.assertIsNotNone(details)


if __name__ == "__main__":
    unittest.main()
