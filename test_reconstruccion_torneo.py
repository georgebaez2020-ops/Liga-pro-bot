import unittest
from reconstruccion_torneo import reconstruir_secuencia


class ReconstruccionTests(unittest.TestCase):
    def setUp(self):
        self.players = ["A", "B", "C", "D"]
        self.matches = [
            {"hora": "16:00", "jugador_a": "A", "jugador_b": "B", "marcador_sets": "3:0"},
            {"hora": "16:30", "jugador_a": "C", "jugador_b": "D", "marcador_sets": "3:2"},
            {"hora": "17:00", "jugador_a": "A", "jugador_b": "C", "marcador_sets": "3:1"},
            {"hora": "17:30", "jugador_a": "B", "jugador_b": "D", "marcador_sets": "3:2"},
            {"hora": "18:00", "jugador_a": "A", "jugador_b": "D", "marcador_sets": "3:0"},
            {"hora": "18:30", "jugador_a": "B", "jugador_b": "C", "marcador_sets": "3:2"},
        ]

    def test_reconstructs_table_in_match_order(self):
        report = reconstruir_secuencia(self.players, self.matches)
        self.assertEqual(report["partidos_reconstruidos"], 6)
        self.assertTrue(report["completa"])
        self.assertEqual(report["secuencia"][0]["tabla_despues"][0]["jugador"], "A")
        self.assertEqual(report["tabla_final_reconstruida"][0]["jugador"], "A")

    def test_rating_delta_and_initial_estimate(self):
        report = reconstruir_secuencia(
            self.players, self.matches,
            {"A": {"rating_final": 610, "variacion": 12},
             "B": {"rating_final": 590, "variacion": -8}}
        )
        self.assertEqual(report["rating_por_jugador"]["A"]["rating_inicial_estimado"], 598)
        self.assertEqual(report["rating_por_jugador"]["B"]["variacion_torneo"], -8)

    def test_rejects_duplicate_pair_and_warns(self):
        matches = self.matches + [self.matches[0]]
        report = reconstruir_secuencia(self.players, matches)
        self.assertEqual(report["partidos_reconstruidos"], 6)
        self.assertTrue(any("duplicado" in x["motivo"] for x in report["advertencias"]))

    def test_incomplete_match_is_not_invented(self):
        matches = self.matches[:-1] + [{"jugador_a": "B", "jugador_b": "C", "marcador_sets": ""}]
        report = reconstruir_secuencia(self.players, matches)
        self.assertEqual(report["partidos_reconstruidos"], 5)
        self.assertFalse(report["completa"])


if __name__ == "__main__":
    unittest.main()
