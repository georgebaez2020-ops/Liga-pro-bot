import unittest
from unittest.mock import patch

import bot_telegram
import tablas_scraper


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


class FakeApp:
    def __init__(self):
        self.bot_data = {"vistas_torneos": {123: {
            "chat_id": 123, "message_id": 456, "wanted": {"live"},
            "heading": "EN VIVO", "last_text": "EN VIVO\nNo hay torneos en esta categoría en la última actualización.",
        }}}
        self.bot = FakeBot()


class TournamentViewsTests(unittest.IsolatedAsyncioTestCase):
    def test_tournament_list_includes_group_table(self):
        tournaments = {"38185": {"estado": "live", "fecha_torneo": "2026-11-19",
            "grupos": [[{"pos": 1, "jugador": "Jugador A", "resultados": ["3:1"],
                "sets": "3:1", "balls": "33:28", "points": 2, "place": 1}]]}}
        text = bot_telegram._formatear_torneos(tournaments, {"live"}, "EN VIVO")
        self.assertIn("Torneo #38185", text)
        self.assertIn("Jugador A", text)
        self.assertIn("Grupo 1", text)

    def test_tournament_list_excludes_old_dates(self):
        tournaments = {
            "today": {"estado": "live", "fecha_torneo": "2026-11-19"},
            "old": {"estado": "live", "fecha_torneo": "2026-11-18"},
            "unknown": {"estado": "upcoming"},
        }
        with patch.object(bot_telegram, "_rango_torneo_hoy",
                          return_value=("2026-11-19", "2026-11-20")):
            rows = bot_telegram._torneos_por_estado(tournaments, {"live", "upcoming"})
        self.assertEqual([tid for tid, _ in rows], ["today"])

    def test_pagination_url_keeps_requested_date_range(self):
        url = "https://tt.league-pro.com/en/tournaments?page=2&status=2"
        filtered = tablas_scraper._aplicar_filtro_fecha(
            url, "2026-11-19", "2026-11-20"
        )
        self.assertIn("page=2", filtered)
        self.assertIn("date_from=2026-11-19", filtered)
        self.assertIn("date_to=2026-11-20", filtered)

    def test_text_is_limited(self):
        text = bot_telegram._texto_telegram("linea\n" * 1000)
        self.assertLessEqual(len(text), 3900)
        self.assertIn("Contenido recortado", text)

    async def test_refresh_edits_only_when_content_changes(self):
        app = FakeApp()
        with patch.object(bot_telegram, "cargar_estado", return_value=(None, [], {})):
            await bot_telegram._actualizar_vistas_torneos(app)
        self.assertEqual(app.bot.edits, [])
        tournaments = {"38185": {"estado": "live", "fecha_torneo": "2026-11-19",
            "grupos": [[{"pos": 1, "jugador": "Jugador A", "resultados": ["3:1"],
                "sets": "3:1", "balls": "33:28", "points": 2, "place": 1}]]}}
        with patch.object(bot_telegram, "cargar_estado", return_value=(None, [], tournaments)):
            await bot_telegram._actualizar_vistas_torneos(app)
        self.assertEqual(len(app.bot.edits), 1)
        self.assertEqual(app.bot.edits[0]["message_id"], 456)
        self.assertIn("Jugador A", app.bot.edits[0]["text"])


if __name__ == "__main__":
    unittest.main()
