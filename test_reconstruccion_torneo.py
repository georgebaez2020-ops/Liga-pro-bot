import unittest
from reconstruccion_torneo import (\n    consolidar_partidos_torneo, parsear_detalle_oficial, reconstruir_secuencia,\n)


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
        report = reconstruir_secuencia(self.players, self.matches + [self.matches[0]])
        self.assertEqual(report["partidos_reconstruidos"], 6)
        self.assertTrue(any("duplicado" in x["motivo"] for x in report["advertencias"]))

    def test_incomplete_match_is_not_invented(self):
        matches = self.matches[:-1] + [{"jugador_a": "B", "jugador_b": "C", "marcador_sets": ""}]
        report = reconstruir_secuencia(self.players, matches)
        self.assertEqual(report["partidos_reconstruidos"], 5)
        self.assertFalse(report["completa"])

    def test_official_tiebreak_uses_game_point_difference_before_head_to_head(self):
        from reconstruccion_torneo import _tabla_ordenada
        names = ["A", "B", "C", "D"]
        points = {"A": 4, "B": 4, "C": 2, "D": 2}
        wins = {"A": 1, "B": 1, "C": 0, "D": 0}
        losses = {"A": 1, "B": 1, "C": 2, "D": 2}
        sets_for = {"A": 5, "B": 5, "C": 3, "D": 3}
        sets_against = {"A": 5, "B": 5, "C": 6, "D": 6}
        gp_for = {"A": 42, "B": 39, "C": 30, "D": 25}
        gp_against = {"A": 40, "B": 41, "C": 40, "D": 45}
        h2h = {frozenset(("A", "B")): "B"}
        table, unresolved = _tabla_ordenada(
            names, points, wins, losses, sets_for, sets_against,
            gp_for, gp_against, h2h
        )
        self.assertEqual([r["jugador"] for r in table[:2]], ["A", "B"])
        self.assertEqual(unresolved, [])

    def test_does_not_apply_head_to_head_before_missing_game_point_criteria(self):
        from reconstruccion_torneo import _tabla_ordenada
        names = ["A", "B", "C", "D"]
        points = {"A": 4, "B": 4, "C": 2, "D": 2}
        wins = {"A": 1, "B": 1, "C": 0, "D": 0}
        losses = {"A": 1, "B": 1, "C": 2, "D": 2}
        sets_for = {"A": 5, "B": 5, "C": 3, "D": 3}
        sets_against = {"A": 5, "B": 5, "C": 6, "D": 6}
        gp_for = {"A": None, "B": None, "C": 30, "D": 25}
        gp_against = {"A": None, "B": None, "C": 40, "D": 45}
        h2h = {frozenset(("A", "B")): "B"}
        table, unresolved = _tabla_ordenada(
            names, points, wins, losses, sets_for, sets_against,
            gp_for, gp_against, h2h
        )
        self.assertEqual({table[0]["jugador"], table[1]["jugador"]}, {"A", "B"})
        self.assertTrue(any(set(x["jugadores"]) == {"A", "B"} for x in unresolved))

    def test_parses_multiline_official_finished_matches(self):
        group = [
            {"jugador": "Picek Petr", "rating": "614"},
            {"jugador": "Stefek Martin", "rating": "558"},
            {"jugador": "Smrcek Milan", "rating": "616"},
            {"jugador": "Andrle Tomas", "rating": "577"},
        ]
        page_text = """Players
#
PLAYER
GAMES
RATING
+/-
-
Picek Petr
4 (1-3)
614
- 10
-
Stefek Martin
4 (2-2)
558
+ 3
-
Smrcek Milan
4 (2-2)
616
+ 8
-
Andrle Tomas
4 (3-1)
577
+ 12
Group
Tournament games
Group
FINISHED
23:59
(614)
Picek P
(558)
Stefek M
1
3
FINISHED
00:30
(616)
Smrcek M
(577)
Andrle T
0
3
for 3rd place
FINISHED
05:00
(616)
Smrcek M
(558)
Stefek M
3
1
Final
FINISHED
05:29
(577)
Andrle T
(614)
Picek P
3
1
"""
        parsed = parsear_detalle_oficial(page_text, group)
        self.assertEqual(len(parsed["partidos"]), 4)
        self.assertEqual(parsed["partidos"][0]["jugador_a"], "Picek Petr")
        self.assertEqual(parsed["partidos"][0]["marcador_sets"], "1:3")
        self.assertEqual(parsed["partidos"][2]["fase"], "third_place")
        self.assertEqual(parsed["partidos"][3]["fase"], "final")
        self.assertEqual(parsed["rating_por_jugador"]["Andrle Tomas"]["variacion"], 12)

    def test_parses_rating_delta_when_sign_and_number_are_separate_lines(self):
        group = [{"jugador": "A", "rating": "500"}, {"jugador": "B", "rating": "510"},
                 {"jugador": "C", "rating": "520"}, {"jugador": "D", "rating": "530"}]
        page_text = """Players
A
4 (3-1)
500
+
12
B
4 (2-2)
510
-
8
C
4 (1-3)
520
+
3
D
4 (0-4)
530
-
15
Group
Tournament games
"""
        parsed = parsear_detalle_oficial(page_text, group)
        self.assertEqual(parsed["rating_por_jugador"]["A"]["variacion"], 12)
        self.assertEqual(parsed["rating_por_jugador"]["B"]["variacion"], -8)
        self.assertEqual(parsed["rating_por_jugador"]["C"]["variacion"], 3)
        self.assertEqual(parsed["rating_por_jugador"]["D"]["variacion"], -15)

    def test_parses_individual_points_from_official_match_card(self):
        group = [
            {"jugador": "Vales Jakub", "rating": "1078"},
            {"jugador": "Zajicek Jan", "rating": "1076"},
            {"jugador": "Medek Josef", "rating": "1102"},
            {"jugador": "Mares Filip", "rating": "1012"},
        ]
        page_text = """Tournament games
Group
FINISHED
20:00
(1078)
Vales J
(1076)
Zajicek J
3
11
11
12
14
1
13
5
10
12
FINISHED
20:30
(1102)
Medek J
(1012)
Mares F
2
8
12
13
12
3
3
11
10
15
10
11
"""
        parsed = parsear_detalle_oficial(page_text, group)
        first, second = parsed["partidos"]
        self.assertEqual(first["marcador_sets"], "3:1")
        self.assertEqual(first["puntos_sets_a"], [11, 11, 12, 14])
        self.assertEqual(first["puntos_sets_b"], [13, 5, 10, 12])
        self.assertEqual((first["puntos_juego_a"], first["puntos_juego_b"]), (48, 40))
        self.assertEqual(second["marcador_sets"], "2:3")
        self.assertEqual(second["puntos_sets_a"], [8, 12, 13, 12, 3])
        self.assertEqual(second["puntos_sets_b"], [11, 10, 15, 10, 11])
        self.assertEqual((second["puntos_juego_a"], second["puntos_juego_b"]), (48, 57))

    def test_parses_upcoming_roster_without_group_table(self):
        page_text = """Players
#
PLAYER
GAMES
RATING
+/-
-
Picek Petr
0 (0-0)
614
+ 10
-
Stefek Martin
0 (0-0)
558
- 3
Tournament games
UPCOMING
23:59
(614)
Picek P
(558)
Stefek M
"""
        parsed = parsear_detalle_oficial(page_text, [])
        self.assertEqual(len(parsed["partidos"]), 1)
        self.assertEqual(parsed["partidos"][0]["estado"], "upcoming")
        self.assertEqual(parsed["partidos"][0]["jugador_a"], "Picek Petr")
        self.assertEqual(parsed["partidos"][0]["jugador_b"], "Stefek Martin")
        self.assertEqual(parsed["rating_por_jugador"]["Picek Petr"]["rating_final"], 614)

    def test_live_partial_score_is_not_treated_as_finished(self):
        group = [{"jugador": "A", "rating": "384"}, {"jugador": "B", "rating": "366"},
                 {"jugador": "C", "rating": "313"}, {"jugador": "D", "rating": "409"}]
        page_text = """Tournament games
Group
LIVE
08:00
(384)
Player A
(366)
Player B
1
2
PLANNED
08:30
(313)
Player C
(409)
Player D
"""
        parsed = parsear_detalle_oficial(page_text, group)
        self.assertEqual(parsed["partidos"][0]["estado"], "live")
        self.assertIsNone(parsed["partidos"][0]["marcador_sets"])
        self.assertEqual(parsed["partidos"][1]["estado"], "planned")
        self.assertIsNone(parsed["partidos"][1]["marcador_sets"])

    def test_consolidates_official_schedule_for_prediction_engine(self):
        analyses = [{
            "grupo": 1,
            "partidos_ficha": [
                {"orden": 1, "estado": "finished", "jugador_a": "A", "jugador_b": "B"},
                {"orden": 2, "estado": "live", "jugador_a": "C", "jugador_b": "D"},
                {"orden": 3, "estado": "planned", "jugador_a": "A", "jugador_b": "C"},
            ],
            "rating_por_jugador": {"A": {"rating_final": 600, "variacion": 5}},
        }]
        result = consolidar_partidos_torneo(analyses)
        self.assertEqual(len(result["partidos"]), 3)
        self.assertEqual(len(result["partidos_programados"]), 1)
        self.assertEqual(len(result["partidos_en_vivo"]), 1)
        self.assertEqual(len(result["partidos_finalizados"]), 1)
        self.assertEqual(result["partidos_programados"][0]["grupo"], 1)
        self.assertEqual(result["rating_por_jugador"]["A"]["rating_final"], 600)

    def test_consolidates_schedule_without_group_table(self):
        result = consolidar_partidos_torneo([], [
            {"orden": 1, "estado": "upcoming", "jugador_a": "A", "jugador_b": "B"}
        ])
        self.assertEqual(len(result["partidos_programados"]), 1)
        self.assertIsNone(result["partidos_programados"][0]["grupo"])


if __name__ == "__main__":
    unittest.main()
