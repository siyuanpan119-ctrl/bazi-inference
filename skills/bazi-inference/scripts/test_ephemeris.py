"""Independent HKO minute-table checks of the raw pinned solar backend."""
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from calendar_engine import HKO_JIE_FIXTURES, EPHEMERIS_COMMIT, jie, jie_approx, solar_term

class EphemerisTests(unittest.TestCase):
    def test_vendor_source_matches_reviewed_commit_digest(self):
        source = Path(__file__).parent / "vendor" / "astronomy.py"
        self.assertEqual(EPHEMERIS_COMMIT,"826e26ff3a6dc03ee46658b1138fef582d96c5d9")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),"41248c7b1edbf9d11119528eef7455a6dc55abde9f1aab40d363015e956c1729")

    def test_raw_backend_matches_24_terms_without_official_overrides(self):
        errors, old_errors = [], []
        for year, rows in HKO_JIE_FIXTURES.items():
            for month,day,hour,minute in rows:
                with self.subTest(year=year,month=month):
                    reference=datetime(year,month,day,hour,minute,tzinfo=timezone(timedelta(hours=8)))
                    raw=jie(year,month)
                    self.assertIn("github.com/cosinekitty/astronomy",raw.source)
                    delta=abs((raw.utc-reference).total_seconds())
                    errors.append(delta)
                    old_errors.append(abs((jie_approx(year,month).utc-reference).total_seconds()))
                    self.assertLess(delta,90)  # fixture gate, not a universal precision claim
        self.assertEqual(len(errors),24)
        self.assertLess(max(errors),max(old_errors))
        self.assertLess(sum(errors),sum(old_errors))

    def test_hko_table_still_has_priority(self):
        table=solar_term(2016,2)
        self.assertEqual(table.utc,datetime(2016,2,4,9,46,tzinfo=timezone.utc))
        self.assertIn("hko.gov.hk",table.source)
        self.assertEqual(table.margin_minutes,1)
        self.assertEqual(jie(2016,2).margin_minutes,30)

    def test_supported_range_endpoints_return_ordered_aware_instants(self):
        for year in (1900,2100):
            terms=[jie(year,month).utc for month in range(1,13)]
            self.assertEqual(terms,sorted(terms))
            self.assertTrue(all(t.year==year and t.tzinfo is not None for t in terms))

if __name__=="__main__":
    unittest.main(verbosity=2)
