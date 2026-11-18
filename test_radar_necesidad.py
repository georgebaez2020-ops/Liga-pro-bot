import unittest
from radar_necesidad import acumular_radar_necesidad, clasificar_necesidad


def group():
    return [{"jugador": n, "resultados": ["", "", "", ""], "sets": "0-0", "balls": "0-0"}
            for n in "ABCD"]


def snap(t, g):
    return {"tournament_id": "T", "captured_at": t,
            "payload": {"grupos": [g]}}


class RadarTests(unittest.TestCase):
    def test_open_match_has_context_for_both_players(self):
        self.assertEqual(set(clasificar_necesidad(group(), 0, 1)), {"A", "B"})

    def test_first_snapshot_is_not_attributed(self):
        g = group()
        g[0]["resultados"][1], g[1]["resultados"][0] = "3:1", "1:3"
        r = acumular_radar_necesidad([snap("2026-11-18T08:00:00", g)])
        self.assertEqual(r["resumen"]["partidos_sin_contexto"], 1)
        self.assertEqual(r["jugadores"], [])

    def test_new_match_is_recorded_once(self):
        before, after = group(), group()
        after[0]["resultados"][1], after[1]["resultados"][0] = "3:0", "0:3"
        r = acumular_radar_necesidad([snap("2026-11-18T08:00:00", before),
                                      snap("2026-11-18T08:05:00", after)])
        self.assertEqual(r["resumen"]["partidos_nuevos"], 1)
        self.assertEqual(r["resumen"]["partidos_con_contexto"], 1)


if __name__ == "__main__":
    unittest.main()
