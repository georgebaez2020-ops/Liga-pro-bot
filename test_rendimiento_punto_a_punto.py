import unittest
from rendimiento_punto_a_punto import construir_perfiles_punto_a_punto


class PointProfileTests(unittest.TestCase):
    def test_aggregates_points_by_player_orientation(self):
        pts = ([{"set": 1, "ganador": "A"}] * 11 +
               [{"set": 2, "ganador": "B"}] * 9)
        report = construir_perfiles_punto_a_punto([{
            "jugador_a": "Ana", "jugador_b": "Beto", "puntos": pts
        }])
        ana = next(x for x in report["jugadores"] if x["jugador"] == "Ana")
        beto = next(x for x in report["jugadores"] if x["jugador"] == "Beto")
        self.assertEqual(ana["puntos_ganados"], 11)
        self.assertEqual(beto["puntos_ganados"], 9)
        self.assertEqual(ana["puntos_jugados"], 20)
        self.assertEqual(beto["puntos_jugados"], 20)

    def test_invalid_sequence_is_not_aggregated(self):
        report = construir_perfiles_punto_a_punto([{
            "jugador_a": "Ana", "jugador_b": "Beto",
            "puntos": [{"set": 1, "ganador": "X"}]
        }])
        self.assertEqual(report["resumen"]["partidos_con_secuencia"], 0)
        self.assertEqual(report["resumen"]["partidos_descartados_o_incompletos"], 1)

    def test_empty_input(self):
        report = construir_perfiles_punto_a_punto([])
        self.assertEqual(report["jugadores"], [])


if __name__ == "__main__":
    unittest.main()
