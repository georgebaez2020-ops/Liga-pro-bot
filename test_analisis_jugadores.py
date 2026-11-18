import unittest
from analisis_jugadores import analyze, score


class PlayerAnalysisTests(unittest.TestCase):
    def test_score_accepts_only_complete_results(self):
        self.assertEqual(score("3 : 1"), (3, 1))
        self.assertIsNone(score(":"))
        self.assertIsNone(score("1 : 1"))
        self.assertIsNone(score("|||"))

    def test_finished_match_must_be_reciprocal(self):
        data = {"torneos": {"T1": {"estado": "finished", "grupos": [[
            {"jugador": "A", "rating": "700", "resultados": ["|||", "3 : 1"]},
            {"jugador": "B", "rating": "690", "resultados": ["1 : 3", "|||"]}
        ]]}}}
        result = analyze(data)
        self.assertEqual(result["validacion"]["duelos_reciprocos_validos"], 1)
        self.assertEqual(result["validacion"]["duelos_inconsistentes"], 0)
        a = next(p for p in result["jugadores"] if p["jugador"] == "A")
        self.assertEqual((a["victorias"], a["derrotas"]), (1, 0))

    def test_live_tournament_is_excluded(self):
        data = {"torneos": {"T1": {"estado": "live", "grupos": [[
            {"jugador": "A", "rating": "700", "resultados": ["|||", "3 : 0"]},
            {"jugador": "B", "rating": "690", "resultados": ["0 : 3", "|||"]}
        ]]}}}
        result = analyze(data)
        self.assertEqual(result["jugadores"], [])


if __name__ == "__main__":
    unittest.main()
