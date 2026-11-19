import unittest

from historial_rendimiento import acumular_historial_presion, acumular_historial_presion_reconstruido
from reconstruccion_torneo import reconstruir_secuencia


def grupo_vacio():
    names = "ABCD"
    return [
        {
            "jugador": name,
            "resultados": ["|||" if i == j else "" for j in range(4)],
            "sets": "0-0",
            "balls": "0-0",
        }
        for i, name in enumerate(names)
    ]


def snapshot(at, group, tid="T1"):
    return {
        "tournament_id": tid,
        "captured_at": at,
        "payload": {"id": tid, "estado": "live", "grupos": [group]},
    }


class HistoricalPressureTests(unittest.TestCase):

    def test_incomplete_snapshots_are_counted_once_and_not_if_later_completed(self):
        incomplete = {"analisis_cronologico": [{
            "grupo": 1, "reconstruccion": {"completa": False, "secuencia": []}
        }]}
        complete = {"analisis_cronologico": [{
            "grupo": 1, "reconstruccion": {"completa": True, "secuencia": []}
        }]}
        snapshots = [
            {"tournament_id": "T11", "captured_at": "2026-11-18T08:00:00Z", "payload": incomplete},
            {"tournament_id": "T11", "captured_at": "2026-11-18T08:05:00Z", "payload": incomplete},
            {"tournament_id": "T11", "captured_at": "2026-11-18T08:10:00Z", "payload": complete},
            {"tournament_id": "T12", "captured_at": "2026-11-18T08:00:00Z", "payload": incomplete},
            {"tournament_id": "T12", "captured_at": "2026-11-18T08:05:00Z", "payload": incomplete},
        ]
        result = acumular_historial_presion_reconstruido(snapshots)
        self.assertEqual(result["resumen"]["grupos_con_reconstruccion_completa"], 1)
        self.assertEqual(result["resumen"]["grupos_incompletos_omitidos"], 1)

    def test_summary_distinguishes_unique_matches_from_player_match_cases(self):
        sequence = [{
            "necesidad_antes": {
                "A": {"debe_ganar_por_puntos_para_seguir_en_fase": True},
                "B": {"debe_ganar_por_puntos_para_seguir_en_fase": True},
            },
            "cumplio_necesidad": {"A": True, "B": False},
        }]
        payload = {"analisis_cronologico": [{
            "grupo": 1,
            "reconstruccion": {"completa": True, "secuencia": sequence},
        }]}
        result = acumular_historial_presion_reconstruido([{
            "tournament_id": "T13", "captured_at": "2026-11-18T08:00:00Z",
            "payload": payload,
        }])
        summary = result["resumen"]
        self.assertEqual(summary["partidos_con_al_menos_un_jugador_obligado"], 1)
        self.assertEqual(summary["casos_jugador_partido_obligado_a_ganar"], 2)
        self.assertEqual(summary["partidos_sin_obligacion_estricta"], 0)

    def test_future_results_do_not_change_need_classification_before_a_match(self):
        players = ["Stefek Martin", "Nohejl Tomas", "Zikmunda Zdenek", "Drabek Zbynek"]
        matches = [
            {"hora": "08:00", "jugador_a": "Stefek Martin", "jugador_b": "Nohejl Tomas", "marcador_sets": "2:3"},
            {"hora": "08:30", "jugador_a": "Zikmunda Zdenek", "jugador_b": "Drabek Zbynek", "marcador_sets": "0:3"},
            {"hora": "09:00", "jugador_a": "Nohejl Tomas", "jugador_b": "Zikmunda Zdenek", "marcador_sets": "3:1"},
            {"hora": "09:30", "jugador_a": "Drabek Zbynek", "jugador_b": "Stefek Martin", "marcador_sets": "3:0"},
            {"hora": "10:00", "jugador_a": "Stefek Martin", "jugador_b": "Zikmunda Zdenek", "marcador_sets": "3:0"},
            {"hora": "10:30", "jugador_a": "Nohejl Tomas", "jugador_b": "Drabek Zbynek", "marcador_sets": "1:3"},
        ]
        original = reconstruir_secuencia(players, matches)
        altered_matches = [dict(match) for match in matches]
        altered_matches[4]["marcador_sets"] = "0:3"
        altered_matches[5]["marcador_sets"] = "3:1"
        altered = reconstruir_secuencia(players, altered_matches)

        original_need = original["secuencia"][3]["necesidad_antes"]["Stefek Martin"]
        altered_need = altered["secuencia"][3]["necesidad_antes"]["Stefek Martin"]
        self.assertTrue(original_need["debe_ganar_por_puntos_para_seguir_en_fase"])
        self.assertEqual(original_need, altered_need)
        self.assertFalse(original["secuencia"][3]["cumplio_necesidad"]["Stefek Martin"])


    def test_uses_complete_reconstruction_for_must_win_history(self):
        sequence = [{
            "jugador_a": "A", "jugador_b": "B", "ganador": "A",
            "necesidad_antes": {
                "A": {"debe_ganar_por_puntos_para_seguir_en_fase": True},
                "B": {"debe_ganar_por_puntos_para_seguir_en_fase": False},
            },
            "cumplio_necesidad": {"A": True, "B": None},
        }]
        payload = {"analisis_cronologico": [{
            "grupo": 1,
            "reconstruccion": {"completa": True, "secuencia": sequence},
        }]}
        result = acumular_historial_presion_reconstruido([{
            "tournament_id": "T9", "captured_at": "2026-11-18T08:00:00Z",
            "payload": payload,
        }])
        self.assertEqual(result["resumen"]["jugadores_obligados_a_ganar"], 1)
        self.assertEqual(result["jugadores"][0]["jugador"], "A")
        self.assertEqual(result["jugadores"][0]["victorias"], 1)
        self.assertEqual(result["jugadores"][0]["tasa_victoria"], 1.0)

    def test_ignores_incomplete_reconstruction(self):
        payload = {"analisis_cronologico": [{
            "grupo": 1,
            "reconstruccion": {"completa": False, "secuencia": [{
                "necesidad_antes": {"A": {"debe_ganar_por_puntos_para_seguir_en_fase": True}},
                "cumplio_necesidad": {"A": True},
            }]},
        }]}
        result = acumular_historial_presion_reconstruido([{
            "tournament_id": "T10", "captured_at": "2026-11-18T08:00:00Z",
            "payload": payload,
        }])
        self.assertEqual(result["jugadores"], [])
        self.assertEqual(result["resumen"]["grupos_incompletos_omitidos"], 1)

    def test_counts_incomplete_group_once_across_snapshots(self):
        payload = {"analisis_cronologico": [{
            "grupo": 1, "reconstruccion": {"completa": False, "secuencia": []},
        }]}
        snapshots = [
            {"tournament_id": "T11", "captured_at": "2026-11-18T08:00:00Z", "payload": payload},
            {"tournament_id": "T11", "captured_at": "2026-11-18T08:05:00Z", "payload": payload},
        ]
        result = acumular_historial_presion_reconstruido(snapshots)
        self.assertEqual(result["resumen"]["grupos_incompletos_omitidos"], 1)

    def test_counts_new_match_once_using_previous_snapshot_context(self):
        before = grupo_vacio()
        after = grupo_vacio()
        after[0]["resultados"][1] = "3:1"
        after[1]["resultados"][0] = "1:3"
        result = acumular_historial_presion([
            snapshot("2026-11-18T08:00:00-05:00", before),
            snapshot("2026-11-18T08:05:00-05:00", after),
            snapshot("2026-11-18T08:10:00-05:00", after),
        ])
        self.assertEqual(result["resumen"]["partidos_nuevos_detectados"], 1)
        self.assertEqual(result["resumen"]["partidos_relevantes"], 1)
        players = {row["jugador"]: row for row in result["jugadores"]}
        self.assertEqual(players["A"]["victorias"], 1)
        self.assertEqual(players["B"]["derrotas"], 1)
        self.assertEqual(players["A"]["partidos_relevantes"], 1)

    def test_first_snapshot_results_are_not_claimed_as_pressure_matches(self):
        group = grupo_vacio()
        group[0]["resultados"][1] = "3:0"
        group[1]["resultados"][0] = "0:3"
        result = acumular_historial_presion([
            snapshot("2026-11-18T08:00:00-05:00", group),
        ])
        self.assertEqual(result["resumen"]["partidos_sin_contexto_previo"], 1)
        self.assertEqual(result["resumen"]["partidos_relevantes"], 0)
        self.assertEqual(result["jugadores"], [])

    def test_different_tournaments_accumulate_same_player(self):
        before1, after1 = grupo_vacio(), grupo_vacio()
        after1[0]["resultados"][1] = "3:0"
        after1[1]["resultados"][0] = "0:3"
        before2, after2 = grupo_vacio(), grupo_vacio()
        after2[0]["resultados"][1] = "1:3"
        after2[1]["resultados"][0] = "3:1"
        result = acumular_historial_presion([
            snapshot("2026-11-18T08:00:00-05:00", before1, "T1"),
            snapshot("2026-11-18T08:05:00-05:00", after1, "T1"),
            snapshot("2026-11-19T08:00:00-05:00", before2, "T2"),
            snapshot("2026-11-19T08:05:00-05:00", after2, "T2"),
        ])
        players = {row["jugador"]: row for row in result["jugadores"]}
        self.assertEqual(players["A"]["partidos_relevantes"], 2)
        self.assertEqual(players["A"]["torneos_con_muestra"], 2)


if __name__ == "__main__":
    unittest.main()
