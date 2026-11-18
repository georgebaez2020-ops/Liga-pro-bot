import unittest

from rendimiento_presion import analizar_rendimiento_presion


def grupo_cuatro():
    scores = [
        ["|||", "3:0", "3:1", "3:2"],
        ["0:3", "|||", "3:1", "3:0"],
        ["1:3", "1:3", "|||", "3:2"],
        ["2:3", "0:3", "2:3", "|||"],
    ]
    return [
        {
            "jugador": name,
            "resultados": scores[i][:],
            "sets": ["9-3", "6-4", "4-6", "2-8"][i],
            "balls": ["100-70", "90-80", "80-90", "70-100"][i],
        }
        for i, name in enumerate("ABCD")
    ]


class PressureProxyTests(unittest.TestCase):
    def test_returns_explicitly_limited_descriptive_metrics(self):
        result = analizar_rendimiento_presion(grupo_cuatro())
        self.assertEqual(result["corte_reglamentario"], "top 2")
        self.assertIn("no una medición psicológica", result["limitaciones"][0])
        self.assertEqual(set(result["jugadores"]), set("ABCD"))
        for row in result["jugadores"].values():
            self.assertFalse(row["muestra_suficiente"])

    def test_incomplete_group_is_rejected(self):
        with self.assertRaises(ValueError):
            analizar_rendimiento_presion(grupo_cuatro()[:3])

    def test_source_group_is_not_mutated(self):
        group = grupo_cuatro()
        original = [row["resultados"][:] for row in group]
        analizar_rendimiento_presion(group)
        self.assertEqual([row["resultados"] for row in group], original)


if __name__ == "__main__":
    unittest.main()
