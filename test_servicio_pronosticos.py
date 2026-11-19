import unittest
from unittest.mock import patch

from servicio_pronosticos import listar_calendario, buscar_jugador
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


    def test_player_search_accepts_name_and_surname_in_either_order(self):
        profiles = [{"jugador": "Biolek Martin", "global": {"partidos": 6}}]
        with patch("servicio_pronosticos.informes", return_value={
            "jugadores": {"jugadores": profiles}
        }):
            self.assertEqual(buscar_jugador("Martin Biolek"), profiles)
            self.assertEqual(buscar_jugador("Biolek Martin"), profiles)

    def test_player_search_is_accent_insensitive(self):
        profiles = [{"jugador": "Martin Bíolek", "global": {"partidos": 6}}]
        with patch("servicio_pronosticos.informes", return_value={
            "jugadores": {"jugadores": profiles}
        }):
            self.assertEqual(buscar_jugador("Biolek Martin"), profiles)


if __name__ == "__main__":
    unittest.main()
