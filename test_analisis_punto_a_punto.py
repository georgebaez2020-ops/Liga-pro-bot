import unittest
from analisis_punto_a_punto import analizar_puntos


class PointByPointTests(unittest.TestCase):
    def test_set_score_and_completion(self):
        pts = [{"set": 1, "ganador": "A"}] * 11 + [{"set": 1, "ganador": "B"}] * 8 + [{"set": 1, "ganador": "A"}]
        r = analizar_puntos(pts)
        self.assertEqual(r["sets"][0]["marcador"], "12:8")
        self.assertTrue(r["todos_los_sets_finalizados"])

    def test_streaks_and_deuce_points(self):
        pts = []
        for _ in range(8):
            pts += [{"set": 1, "ganador": "A"}, {"set": 1, "ganador": "B"}]
        pts += [{"set": 1, "ganador": "A"}] * 3
        pts += [{"set": 1, "ganador": "B"}] * 3
        r = analizar_puntos(pts)
        self.assertEqual(r["racha_maxima"], {"A": 8, "B": 8})
        self.assertEqual(r["puntos_ganados_desde_8_8"], {"A": 3, "B": 3})

    def test_two_sets_and_incomplete_set(self):
        pts = [{"set": 1, "ganador": "A"}] * 11 + [{"set": 2, "ganador": "B"}] * 9
        r = analizar_puntos(pts)
        self.assertEqual(r["sets_observados"], 2)
        self.assertEqual([s["marcador"] for s in r["sets"]], ["11:0", "0:9"])
        self.assertFalse(r["todos_los_sets_finalizados"])

    def test_invalid_point_is_reported(self):
        r = analizar_puntos([{"set": 1, "ganador": "X"}])
        self.assertEqual(len(r["advertencias"]), 1)


if __name__ == "__main__":
    unittest.main()
