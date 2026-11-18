import unittest

from inteligencia_torneo import (
    analizar_torneo, calcular_clasificacion, calcular_partidos_pendientes,
    evaluar_necesidad_jugador,
)


def grupo_cuatro():
    # A vence a B/C/D; B vence a C/D; C vence a D.
    scores = [
        ["|||", "3 : 0", "3 : 1", "3 : 2"],
        ["0 : 3", "|||", "3 : 1", "3 : 0"],
        ["1 : 3", "1 : 3", "|||", "3 : 2"],
        ["2 : 3", "0 : 3", "2 : 3", "|||"],
    ]
    rows = []
    for i, name in enumerate("ABCD"):
        rows.append({
            "jugador": name, "rating": "700",
            "resultados": scores[i],
            "sets": ["9-3", "6-4", "4-6", "2-8"][i],
            "balls": ["100-70", "90-80", "80-90", "70-100"][i],
        })
    return rows


class TournamentIntelligenceTests(unittest.TestCase):
    def test_four_player_points_and_final_stage_objectives(self):
        table = calcular_clasificacion(grupo_cuatro())
        self.assertEqual([r["jugador"] for r in table["clasificacion"]], ["A", "B", "C", "D"])
        self.assertEqual(table["clasificacion"][0]["puntos_reglamento"], 6)
        self.assertEqual(table["estado_clasificacion"], "completa")
        self.assertEqual(
            evaluar_necesidad_jugador(table, "A")["objetivo_reglamentario"],
            "disputar la final por el título",
        )
        self.assertEqual(
            evaluar_necesidad_jugador(table, "C")["objetivo_reglamentario"],
            "disputar el partido por el tercer puesto",
        )

    def test_five_player_last_place_targets_top_four(self):
        group = grupo_cuatro() + [{
            "jugador": "E", "rating": "650",
            "resultados": ["", "", "", "", "|||"],
            "sets": "0-0", "balls": "0-0",
        }]
        # Esta prueba valida el objetivo por formato; los duelos E aún pendientes.
        table = calcular_clasificacion(group)
        need = evaluar_necesidad_jugador(table, "E")
        self.assertEqual(table["formato"], 5)
        self.assertEqual(need["referencia"], "top 4")
        self.assertTrue(need["requiere_atencion"])

    def test_missing_and_non_reciprocal_scores_are_not_counted(self):
        group = grupo_cuatro()
        group[0]["resultados"][1] = ""
        group[1]["resultados"][0] = ""
        pending = calcular_partidos_pendientes(group)
        self.assertEqual(len(pending["pendientes"]), 1)
        table = calcular_clasificacion(group)
        self.assertEqual(table["estado_clasificacion"], "provisional")

    def test_tournament_output_does_not_claim_final_ranking(self):
        result = analizar_torneo({"id": "T1", "estado": "finished", "grupos": [grupo_cuatro()]})
        self.assertFalse(result["fase_final_disponible"])
        self.assertIn("puesto definitivo", result["advertencia_fase_final"])


if __name__ == "__main__":
    unittest.main()
