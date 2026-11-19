import unittest

from tablas_scraper import enriquecer_marcadores_live


class _Body:
    def __init__(self, page):
        self.page = page

    async def inner_text(self):
        return self.page.text_by_url[self.page.current_url]


class _Page:
    def __init__(self, text_by_url):
        self.text_by_url = text_by_url
        self.current_url = None

    async def evaluate(self, _script, _torneo_id):
        return list(self.text_by_url)

    async def goto(self, url, **_kwargs):
        self.current_url = url

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"Selector inesperado: {selector}")
        return _Body(self)


class EnriquecerMarcadoresLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_enriches_only_unambiguous_live_matches_from_official_pages(self):
        url_ok = "https://tt.league-pro.com/en/tournaments/123/456"
        url_ambiguous = "https://tt.league-pro.com/en/tournaments/123/457"
        page = _Page({
            url_ok: "Match\\nFranek T\\n1:2\\nSkakal M\\n",
            url_ambiguous: "Match\\nHrabec J\\n0:1\\nHrabec Jan\\n",
        })
        matches = [
            {"estado": "live", "jugador_a": "Franek Tomas", "jugador_b": "Skakal Martin"},
            {"estado": "live", "jugador_a": "Hrabec Jan", "jugador_b": "Hrabec Jiri"},
            {"estado": "finished", "jugador_a": "A", "jugador_b": "B", "marcador_sets": "3:1"},
        ]

        result = await enriquecer_marcadores_live(page, "123", matches)

        self.assertEqual(result, {"consultados": 2, "actualizados": 1})
        self.assertEqual(matches[0]["marcador_live_sets"], "1:2")
        self.assertEqual(matches[0]["fuente_marcador_live"], url_ok)
        self.assertNotIn("marcador_live_sets", matches[1])
        self.assertNotIn("marcador_live_sets", matches[2])

    async def test_skips_page_lookup_when_there_are_no_live_matches_missing_score(self):
        page = _Page({})
        matches = [
            {"estado": "live", "jugador_a": "A", "jugador_b": "B", "marcador_live_sets": "0:0"},
            {"estado": "finished", "jugador_a": "C", "jugador_b": "D"},
        ]

        result = await enriquecer_marcadores_live(page, "123", matches)

        self.assertEqual(result, {"consultados": 0, "actualizados": 0})


if __name__ == "__main__":
    unittest.main()
