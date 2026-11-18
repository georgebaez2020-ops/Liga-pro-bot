import unittest

from inspeccionar_hoja_partido import validar_url


class InspeccionarHojaPartidoTests(unittest.TestCase):
    def test_accepts_official_match_url(self):
        url = "https://tt.league-pro.com/en/tournaments/37944/320262"
        self.assertEqual(validar_url(url), url)

    def test_rejects_non_official_host(self):
        with self.assertRaises(ValueError):
            validar_url("https://example.com/en/tournaments/37944/320262")

    def test_rejects_tournament_page_without_match_id(self):
        with self.assertRaises(ValueError):
            validar_url("https://tt.league-pro.com/en/tournaments/37944")


if __name__ == "__main__":
    unittest.main()
