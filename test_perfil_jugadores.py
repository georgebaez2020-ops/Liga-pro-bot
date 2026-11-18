import unittest

from perfil_jugadores import construir_perfiles, extraer_partidos_historicos


def group(score=None):
    names = ["Ana", "Beto", "Ciro", "Dani"]
    rows = []
    for i, name in enumerate(names):
        results = ["" for _ in names]
        results[i] = "---"
        rows.append({"jugador": name, "resultados": results, "rating": str(1000+i)})
    if score:
        a, b, value = score
        rows[a]["resultados"][b] = value
        left, right = map(int, value.split(":"))
        rows[b]["resultados"][a] = f"{right}:{left}"
    return rows


def snap(at, rows):
    return {"tournament_id": "T1", "captured_at": at,
            "payload": {"grupos": [rows]}}


class PlayerProfileTests(unittest.TestCase):
    def test_deduplicates_repeated_snapshots(self):
        rows = group((0, 1, "3:1"))
        matches = extraer_partidos_historicos([
            snap("2026-11-18T08:00:00-05:00", rows),
            snap("2026-11-18T08:10:00-05:00", rows),
        ])
        self.assertEqual(len(matches), 1)

    def test_ignores_partial_scores_and_requires_reciprocal(self):
        rows = group((0, 1, "1:0"))
        self.assertEqual(extraer_partidos_historicos([snap("2026-11-18", rows)]), [])
        rows = group((0, 1, "3:1"))
        rows[1]["resultados"][0] = "0:3"
        self.assertEqual(extraer_partidos_historicos([snap("2026-11-18", rows)]), [])

    def test_builds_player_windows_and_head_to_head(self):
        rows = group((0, 1, "3:2"))
        report = construir_perfiles([snap("2026-11-18", rows)])
        self.assertEqual(report["resumen"]["partidos_unicos_completos"], 1)
        ana = next(p for p in report["jugadores"] if p["jugador"] == "Ana")
        self.assertEqual(ana["global"]["victorias"], 1)
        self.assertEqual(ana["ventanas"]["10"]["partidos"], 1)
        self.assertEqual(report["h2h"][0]["partidos"], 1)


if __name__ == "__main__":
    unittest.main()

# CI trigger: execute historical profile unit tests on the development branch.
