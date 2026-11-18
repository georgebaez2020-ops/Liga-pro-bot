import unittest
from motor_pronosticos import pronosticar_partido


def make_snapshot(tid, captured, winner_a=True):
    names = ["Ana", "Beto", "Ciro", "Dora"]
    group = [{"jugador": name, "rating": "1500", "resultados": [""] * 4} for name in names]
    for i in range(4):
        for j in range(i + 1, 4):
            a_wins = winner_a if (i, j) == (0, 1) else (i < j)
            score = ("3:1", "1:3") if a_wins else ("1:3", "3:1")
            group[i]["resultados"][j] = score[0]
            group[j]["resultados"][i] = score[1]
    return {
        "tournament_id": tid, "captured_at": captured, "status": "finished",
        "payload": {"torneo": {"grupos": [group]}},
    }


class PredictionEngineTests(unittest.TestCase):
    def setUp(self):
        self.snapshots = [
            make_snapshot(f"t{i}", f"2026-10-{i:02d}T12:00:00+00:00")
            for i in range(1, 7)
        ]

    def test_probabilities_sum_to_one_hundred(self):
        result = pronosticar_partido(self.snapshots, "Ana", "Beto", fecha_partido="2026-11-01T00:00:00+00:00")
        self.assertTrue(result["elegible"])
        self.assertAlmostEqual(result["probabilidad_a"] + result["probabilidad_b"], 100.0)

    def test_rejects_insufficient_history(self):
        result = pronosticar_partido(self.snapshots[:2], "Ana", "Beto", fecha_partido="2026-11-01T00:00:00+00:00")
        self.assertFalse(result["elegible"])
        self.assertEqual(result["motivo"], "muestra_historica_insuficiente")

    def test_rejects_live_match(self):
        result = pronosticar_partido(self.snapshots, "Ana", "Beto", estado="live")
        self.assertFalse(result["elegible"])
        self.assertEqual(result["motivo"], "solo_partidos_no_iniciados")

    def test_requires_prediction_cutoff(self):
        result = pronosticar_partido(self.snapshots, "Ana", "Beto")
        self.assertFalse(result["elegible"])
        self.assertEqual(result["motivo"], "fecha_partido_con_zona_horaria_requerida")

    def test_names_are_normalized(self):
        result = pronosticar_partido(self.snapshots, " ANA ", "Beto", fecha_partido="2026-11-01T00:00:00+00:00")
        self.assertTrue(result["elegible"])


if __name__ == "__main__":
    unittest.main()
