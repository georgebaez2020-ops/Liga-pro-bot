import unittest
from unittest.mock import patch

from servicio_pronosticos import listar_calendario


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


if __name__ == "__main__":
    unittest.main()
