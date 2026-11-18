import os
import tempfile
import unittest

from db import HistoryDB
from retroalimentacion import PredictionFeedback


def snapshot(captured_at, score_a="3:1"):
    names = ["Ana", "Beto", "Ciro", "Dora"]
    group = [{"jugador": name, "resultados": [""] * 4} for name in names]
    group[0]["resultados"][1] = score_a
    group[1]["resultados"][0] = "1:3" if score_a == "3:1" else "3:1"
    return {
        "tournament_id": "torneo-1",
        "captured_at": captured_at,
        "payload": {"torneo": {"grupos": [group]}},
    }


class PredictionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = HistoryDB(sqlite_path=os.path.join(self.tmp.name, "history.sqlite"))
        self.feedback = PredictionFeedback(self.db)
        self.match = {
            "torneo_id": "torneo-1", "grupo": 1,
            "jugador_a": "Ana", "jugador_b": "Beto",
            "fecha": "2026-11-20T12:00:00+00:00",
        }
        self.forecast = {
            "elegible": True, "jugador_a": "Ana", "jugador_b": "Beto",
            "probabilidad_a": 65.0, "probabilidad_b": 35.0,
            "confianza_muestra": 0.6,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_once_and_settles_only_after_prediction(self):
        pid = self.feedback.record(self.match, self.forecast,
                                   predicted_at="2026-11-20T10:00:00+00:00")
        self.assertEqual(pid, self.feedback.record(
            self.match, self.forecast, predicted_at="2026-11-20T10:00:00+00:00"))
        before = self.feedback.settle_from_snapshots([
            snapshot("2026-11-20T09:00:00+00:00", score_a="")
        ])
        self.assertEqual(before["liquidados"], 0)
        after = self.feedback.settle_from_snapshots([
            snapshot("2026-11-20T09:00:00+00:00"),
            snapshot("2026-11-20T12:30:00+00:00"),
        ])
        self.assertEqual(after["liquidados"], 1)
        metrics = self.feedback.metrics()
        self.assertEqual(metrics["muestra"], 1)
        self.assertAlmostEqual(metrics["brier"], 0.1225)

    def test_invalid_probabilities_are_rejected(self):
        bad = dict(self.forecast, probabilidad_b=40.0)
        with self.assertRaises(ValueError):
            self.feedback.record(self.match, bad)

    def test_pending_prediction_is_not_settled_without_confirmed_result(self):
        self.feedback.record(self.match, self.forecast,
                             predicted_at="2026-11-20T10:00:00+00:00")
        result = self.feedback.settle_from_snapshots([
            snapshot("2026-11-20T12:30:00+00:00", score_a="")
        ])
        self.assertEqual(result["liquidados"], 0)


if __name__ == "__main__":
    unittest.main()
