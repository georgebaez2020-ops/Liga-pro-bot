import json
import os
import tempfile
import unittest

from db import HistoryDB


class HistoryDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = HistoryDB(database_url="", sqlite_path=os.path.join(self.tmp.name, "history.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def sample(self):
        return {
            "generado": "2026-11-18T08:00:00-05:00",
            "dia_colombia": "2026-11-18",
            "torneos": {
                "38185": {
                    "estado": "upcoming",
                    "texto_listado": "18 Nov 08:00 UPCOMING",
                    "grupos": []
                }
            }
        }

    def test_upcoming_without_groups_is_saved_and_can_be_updated(self):
        first = self.db.save_scrape(self.sample())
        self.assertEqual(first["torneos"], 1)
        self.assertEqual(first["participaciones"], 0)

        later = self.sample()
        later["generado"] = "2026-11-18T08:10:00-05:00"
        later["torneos"]["38185"]["grupos"] = [[
            {"jugador": "Jugador A", "pos": "1", "rating": "700",
             "resultados": ["|||", "3 : 1"], "sets": "3:1"},
            {"jugador": "Jugador B", "pos": "2", "rating": "690",
             "resultados": ["1 : 3", "|||"], "sets": "1:3"}
        ]]
        second = self.db.save_scrape(later)
        self.assertEqual(second["participaciones"], 2)
        self.assertEqual(second["partidos_validos"], 1)

        with self.db._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tournament_snapshots").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 1)

    def test_listar_snapshots_returns_chronological_payloads(self):
        first = self.sample()
        self.db.save_scrape(first)
        later = self.sample()
        later["generado"] = "2026-11-18T08:10:00-05:00"
        self.db.save_scrape(later)
        snapshots = self.db.listar_snapshots()
        self.assertEqual(len(snapshots), 2)
        self.assertLess(snapshots[0]["captured_at"], snapshots[1]["captured_at"])
        self.assertEqual(snapshots[0]["payload"]["estado"], "upcoming")

    def test_duplicate_snapshot_does_not_duplicate_records(self):
        data = self.sample()
        self.db.save_scrape(data)
        result = self.db.save_scrape(data)
        self.assertEqual(result["torneos"], 1)
        with self.db._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tournament_snapshots").fetchone()[0], 1)


    def test_historical_backfill_is_idempotent_by_official_date(self):
        tournament = {
            "id": "99001", "estado": "finished", "fecha_torneo": "2026-01-31",
            "grupos": [[
                {"jugador": "Hist A", "pos": "1", "rating": "700",
                 "resultados": ["|||", "3 : 1"], "sets": "3:1"},
                {"jugador": "Hist B", "pos": "2", "rating": "690",
                 "resultados": ["1 : 3", "|||"], "sets": "1:3"}
            ]]
        }
        first = self.db.save_historical_scrape(tournament)
        second = self.db.save_historical_scrape(tournament)
        self.assertEqual(first["snapshots"], 1)
        self.assertEqual(second["snapshots"], 1)
        snapshots = self.db.listar_snapshots()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["payload"]["fecha_torneo"], "2026-01-31")

    def test_historical_backfill_requires_official_date(self):
        with self.assertRaises(ValueError):
            self.db.save_historical_scrape({"id": "99002", "grupos": []})

if __name__ == "__main__":
    unittest.main()
