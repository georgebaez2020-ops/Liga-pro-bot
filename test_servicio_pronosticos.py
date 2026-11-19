import unittest

from servicio_pronosticos import (
    listar_calendario, formatear_resumen_torneos, formatear_tablas_torneos,
)
from reconstruccion_torneo import parsear_detalle_oficial


class PredictionServiceTests(unittest.TestCase):
    def test_calendar_keeps_upcoming_and_live_without_inventing_schedule(self):
        tournaments = {
            "T1": {
                "partidos_programados": [
                    {"estado": "planned", "jugador_a": "Ana", "jugador_b": "Beto", "hora": "12:00", "grupo": 1},
                    {"estado": "live", "jugador_a": "Ciro", "jugador_b": "Dora", "hora": "12:30", "grupo": 1},
                ]
            }
        }
        rows = listar_calendario(tournaments)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["torneo_id"], "T1")
        self.assertIsNone(rows[0].get("scheduled_at"))

    def test_calendar_fallback_filters_statuses(self):
        tournaments = {
            "T2": {
                "partidos": [
                    {"estado": "finished", "jugador_a": "A", "jugador_b": "B"},
                    {"estado": "upcoming", "jugador_a": "C", "jugador_b": "D"},
                ]
            }
        }
        rows = listar_calendario(tournaments)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["estado"], "upcoming")

    def test_live_tournament_summary_and_group_table_formatting(self):
        result = {
            "dia_colombia": "2026-11-18",
            "torneos": {
                "123": {
                    "estado": "live",
                    "fecha_torneo": "2026-11-18",
                    "grupos": [[{"jugador": "Ana"}]],
                    "partidos_finalizados": [
                        {"fase": "group", "grupo": 1, "jugador_a": "Ana",
                         "jugador_b": "Beto", "marcador_sets": "3:1"}
                    ],
                    "partidos_en_vivo": [
                        {"fase": "group", "grupo": 1, "jugador_a": "Ciro",
                         "jugador_b": "Dora", "marcador_sets": None}
                    ],
                    "inteligencia": {
                        "grupos": [{
                            "grupo": 1,
                            "estado_clasificacion": "provisional",
                            "clasificacion": [{
                                "puesto_grupo": 1, "jugador": "Ana",
                                "partidos": 2, "victorias": 2, "derrotas": 0,
                                "puntos_reglamento": 4,
                            }],
                            "partidos_pendientes": [{"jugador_a": "Ana", "jugador_b": "Beto"}],
                            "marcadores_inconsistentes": [],
                        }]
                    },
                },
                "456": {
                    "estado": "upcoming",
                    "fecha_torneo": "2026-11-18",
                    "grupos": [],
                },
            },
        }
        summary = formatear_resumen_torneos(result)
        table = formatear_tablas_torneos(result)
        self.assertIn("ID 123 | LIVE", summary)
        self.assertIn("Grupo 1 — PROVISIONAL", table)
        self.assertIn("Ana | 2 | 2 | 0 | 4", table)
        self.assertIn("pendientes: 1", table)
        self.assertIn("RESULTADOS FINALIZADOS", table)
        self.assertIn("Ana 3:1 Beto", table)
        self.assertIn("PARTIDOS EN JUEGO", table)
        self.assertIn("Ciro vs Dora", table)
        self.assertNotIn("456", table)
        self.assertNotIn("UPCOMING", table)

    def test_tables_without_live_tournaments_say_none_are_active(self):
        result = {"torneos": {"456": {"estado": "upcoming", "grupos": []}}}
        table = formatear_tablas_torneos(result)
        self.assertIn("No hay torneos LIVE", table)

    def test_official_tournament_date_is_extracted(self):
        parsed = parsear_detalle_oficial(
            "Players\nPlayer\nTournament games\nGroup\n17 Nov 2026\nTuesday\n08:00",
            [],
        )
        self.assertEqual(parsed["fecha_torneo"], "2026-11-17")

    def test_missing_official_date_remains_unknown(self):
        parsed = parsear_detalle_oficial("Players\nTournament games\nPlanned\n08:00", [])
        self.assertIsNone(parsed["fecha_torneo"])
        self.assertTrue(any("fecha oficial" in x.get("motivo", "") for x in parsed["advertencias"]))


if __name__ == "__main__":
    unittest.main()
