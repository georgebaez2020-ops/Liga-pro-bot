import unittest

from backfill_historico import extraer_id_torneo


class BackfillHistoricoTests(unittest.TestCase):
    def test_extrae_id_de_url_absoluta(self):
        self.assertEqual(
            extraer_id_torneo("https://tt.league-pro.com/en/tournaments/38185"),
            "38185",
        )

    def test_extrae_id_de_url_relativa_con_query(self):
        self.assertEqual(
            extraer_id_torneo("/en/tournaments/38185/?source=archive"),
            "38185",
        )

    def test_rechaza_rutas_que_no_son_ids_numericos(self):
        self.assertIsNone(extraer_id_torneo("/en/tournaments/abc"))
        self.assertIsNone(extraer_id_torneo("/en/tournaments/38185x"))
        self.assertIsNone(extraer_id_torneo("/en/players/38185"))


if __name__ == "__main__":
    unittest.main()
