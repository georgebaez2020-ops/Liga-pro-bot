import unittest
from reconstruccion_torneo import parsear_detalle_oficial, reconstruir_secuencia


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

    def test_parses_official_players_rating_and_games(self):
        group = [
            {"jugador": "Biolek Martin", "rating": "1090"},
            {"jugador": "Szotkowski Jan", "rating": "1070"},
            {"jugador": "Dzida Jan", "rating": "1076"},
            {"jugador": "Zika Tadeas", "rating": "1081"},
        ]
        page_text = (
            "Players Player Games Rating +/- "
            "Dzida Jan 1 4 (3-1) 1076 + 12 "
            "Zika Tadeas 2 4 (2-2) 1081 + 2 "
            "Szotkowski Jan 3 4 (2-2) 1070 + 8 "
            "Biolek Martin 4 4 (1-3) 1090 - 21 "
            "Group 12 Nov 2026 Tournament games Group "
            "Finished 16:00 (1090)Biolek M(1070)Szotkowski J 1 3 "
            "Finished 16:30 (1076)Dzida J(1081)Zika T 0 3"
        )
        parsed = parsear_detalle_oficial(page_text, group)
        self.assertEqual(len(parsed["partidos"]), 2)
        self.assertEqual(parsed["partidos"][0]["jugador_a"], "Biolek Martin")
        self.assertEqual(parsed["rating_por_jugador"]["Biolek Martin"]["variacion"], -21)


if __name__ == "__main__":
    unittest.main()
