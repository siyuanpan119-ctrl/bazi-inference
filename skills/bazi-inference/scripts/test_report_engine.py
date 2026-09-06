"""Report interfaces, provenance and ambiguity gates; not predictive-validity tests."""
import json
import unittest
from copy import deepcopy
from datetime import datetime

from report_engine import generate_report, resolve_birthplace, stem_relations


def request(**values):
    return {"synthetic": True, "birth_datetime": "2000-01-01T12:30", "sex": "male", "birthplace": "香港", **values}


class ResolutionTests(unittest.TestCase):
    def test_country_alone_not_replaced_with_capital(self):
        for value in ("美国", "马来西亚", "台湾", "中国大陆", "Atlantis"):
            with self.subTest(value=value):
                result = generate_report(request(birthplace=value), as_of="2022-01-01")
                self.assertEqual(result["status"], "needs_resolution")
                self.assertNotIn("chart", result)

    def test_reviewed_city_aliases_and_regional_malaysia_zones(self):
        for city, zone in (("Hong Kong","Asia/Hong_Kong"),("臺北","Asia/Taipei"),
                           ("Beijing","Asia/Shanghai"),("Kuala Lumpur","Asia/Kuala_Lumpur"),
                           ("Kota Kinabalu","Asia/Kuching")):
            resolved = resolve_birthplace(city, 2000)
            self.assertEqual(resolved["timezone"],zone)
            self.assertTrue(resolved["timezone_source"].startswith("https://data.iana.org/"))

    def test_mainland_city_does_not_inherit_shanghai_early_history(self):
        self.assertEqual(resolve_birthplace("北京",1940)["status"],"needs_resolution")

    def test_external_resolution_needs_source(self):
        result = generate_report(request(birthplace={"city":"Paris", "timezone":"Europe/Paris"}),as_of="2022-01-01")
        self.assertEqual(result["status"],"needs_resolution")
        value = {"city":"Paris", "timezone":"Europe/Paris", "timezone_source":"https://data.iana.org/time-zones/tzdb/europe"}
        result = generate_report(request(birthplace=value),as_of="2022-01-01")
        self.assertEqual(result["status"],"ready_with_limitations")
        self.assertEqual(result["birthplace_resolution"]["resolution"],"caller_asserted_with_source")

    def test_date_alone_and_lunar_date_are_not_silently_accepted(self):
        for values in ({"birth_datetime":"2000-01-01"},{"calendar":"lunar"}):
            result = generate_report(request(**values),as_of="2022-01-01")
            self.assertEqual(result["status"],"needs_resolution")
            self.assertNotIn("chart",result)

    def test_missing_fields_return_specific_resolution(self):
        result = generate_report({"sex":"male"},as_of="2022-01-01")
        self.assertEqual(result["missing"],["birth_datetime","birthplace"])

    def test_synthetic_flag_and_original_request_survive_without_mutation(self):
        original = request()
        before = deepcopy(original)
        result = generate_report(original,as_of="2022-01-01")
        self.assertEqual(original,before)
        self.assertEqual(result["input"],original)
        self.assertTrue(result["synthetic"])
        json.dumps(result,ensure_ascii=False,allow_nan=False)


class ReportTests(unittest.TestCase):
    def test_report_uses_explicit_observation_year_not_system_clock(self):
        result = generate_report(request(),as_of="2013-05-06")
        self.assertEqual(result["annual_reports"][0]["solar_year"],2013)
        self.assertEqual(result["as_of"],"2013-05-06")
        self.assertEqual(result["conventions"]["time_basis"],"standard")

    def test_missing_as_of_rejected(self):
        with self.assertRaises(ValueError):
            generate_report(request(),as_of="")

    def test_hko_annual_interval_and_twelve_months(self):
        result = generate_report(request(),as_of="2016-05-01",years=[2016])
        annual = result["annual_reports"][0]
        self.assertEqual(annual["pillar"],"丙申")
        self.assertEqual(annual["interval"]["start"]["utc"],"2016-02-04T09:46:00+00:00")
        self.assertEqual(len(annual["months"]),12)
        self.assertEqual(annual["months"][0]["pillar"],"庚寅")
        self.assertEqual(annual["months"][-1]["pillar"],"辛丑")
        for a,b in zip(annual["months"],annual["months"][1:]):
            self.assertEqual(a["ends_at_jie"]["utc"],b["starts_at_jie"]["utc"])
        self.assertEqual(annual["months"][-1]["ends_at_jie"]["utc"],annual["interval"]["end"]["utc"])

    def test_dayun_intervals_cover_ten_elapsed_years(self):
        result = generate_report(request(),as_of="2022-01-01")
        self.assertEqual(len(result["dayun"]),9)
        self.assertEqual(result["dayun"][0]["start_utc_approx"],result["chart"]["luck"]["start_utc_approx"])
        for c in result["dayun"]:
            days=(datetime.fromisoformat(c["end_utc_approx"])-datetime.fromisoformat(c["start_utc_approx"])).total_seconds()/86400
            self.assertAlmostEqual(days,3652.425,5)
        for a,b in zip(result["dayun"],result["dayun"][1:]):
            self.assertEqual(a["end_utc_approx"],b["start_utc_approx"])

    def test_year_spanning_dayun_change_contains_both(self):
        initial = generate_report(request(),as_of="2040-01-01")
        # Use an actual engine-produced switch, then ensure the annual selector
        # doesn't flatten an entire year to the luck active at its beginning.
        year = datetime.fromisoformat(initial["dayun"][2]["start_utc_approx"]).year
        result = generate_report(request(),as_of="2040-01-01",years=[year])
        self.assertGreaterEqual(len(result["annual_reports"][0]["dayun_segments"]),2)

    def test_month_crossing_luck_transition_keeps_both_combined_relations(self):
        initial = generate_report(request(),as_of="2040-01-01")
        switch = datetime.fromisoformat(initial["dayun"][2]["start_utc_approx"])
        result = generate_report(request(),as_of="2040-01-01",years=[switch.year])
        month = next(m for m in result["annual_reports"][0]["months"]
                     if datetime.fromisoformat(m["starts_at_jie"]["utc"]) <= switch < datetime.fromisoformat(m["ends_at_jie"]["utc"]))
        segments=month["dayun_segments"]
        self.assertEqual({s["sequence"] for s in segments},{2,3})
        self.assertEqual(segments[0]["overlap_end_utc_approx"],switch.isoformat())
        self.assertEqual(segments[1]["overlap_start_utc_approx"],switch.isoformat())
        self.assertIn("relations",month)
        for s in segments:
            all_labels={label for r in s["relations"]["stems"] for label in r["labels"]}
            self.assertTrue({"年柱","月柱","日柱","时柱","大运","流年","流月"} <= all_labels)
            self.assertIn("luck_start_date_margin_days_operational",s)

    def test_strict_birth_boundary_withholds_single_chart_reading(self):
        result = generate_report(request(birth_datetime="2016-02-04T17:46"),as_of="2022-01-01")
        self.assertEqual(result["status"],"needs_verification")
        self.assertEqual(result["annual_reports"],[])
        self.assertEqual(result["dayun"],[])
        self.assertTrue(result["chart"]["nominal_pillars_only"])

    def test_dst_changes_are_visible_to_host_ai(self):
        result = generate_report(request(birth_datetime="1990-06-12T17:30",birthplace="北京"),as_of="2022-01-01")
        self.assertEqual(result["chart"]["pillars"]["hour"][1],"申")
        civil = next(x for x in result["time_basis_alternatives"] if x["time_basis"]=="civil")
        self.assertEqual(civil["pillars"]["hour"][1],"酉")
        self.assertTrue(result["interpretation_must_be_conditional_on_time_convention"])

    def test_unknown_solar_longitude_not_substituted(self):
        result = generate_report(request(birthplace="北京"),as_of="2022-01-01")
        solar = next(x for x in result["time_basis_alternatives"] if x["time_basis"]=="apparent_solar")
        self.assertEqual(solar["status"],"needs_longitude")

    def test_zi23_alternative_is_explicit(self):
        result = generate_report(request(birth_datetime="2000-01-01T23:30"),as_of="2022-01-01")
        self.assertEqual(result["day_boundary_alternative"]["day_boundary"],"zi23")
        self.assertNotEqual(result["day_boundary_alternative"]["pillars"]["day"],result["chart"]["pillars"]["day"])

    def test_stem_production_control_direction_and_no_automatic_transformation(self):
        relations = stem_relations(["甲","丙","戊","庚","壬","己"])
        pairs = {(r["kind"],r["stems"]) for r in relations}
        for pair in (("生","甲丙"),("生","丙戊"),("生","戊庚"),("生","庚壬"),("生","壬甲"),
                     ("克","甲戊"),("克","戊壬"),("克","壬丙"),("克","丙庚"),("克","庚甲")):
            self.assertIn(pair,pairs)
        combination = next(r for r in relations if r["kind"]=="天干五合配对")
        self.assertFalse(combination["transformation_claimed"])

    def test_specific_diagnoses_and_event_predictions_not_generated(self):
        result = generate_report(request(),as_of="2022-01-01")
        a = result["annual_reports"][0]
        self.assertEqual(a["traditional_observation"]["claim_status"],"traditional_hypothesis_not_empirical_prediction")
        self.assertNotIn("event_predictions",result)
        self.assertIn("birthplace_resolution",result)
        self.assertIn("原局格局",result["report_markdown"])

    def test_requested_year_before_birth_rejected(self):
        with self.assertRaisesRegex(ValueError,"before birth"):
            generate_report(request(),as_of="2022-01-01",years=[1990])

    def test_gap_time_is_returned_for_resolution_not_silently_shifted(self):
        place={"city":"New York", "timezone":"America/New_York", "timezone_source":"https://data.iana.org/time-zones/tzdb/northamerica"}
        result=generate_report(request(birth_datetime="2024-03-10T02:30",birthplace=place),as_of="2024-12-01")
        self.assertEqual(result["status"],"needs_resolution")
        self.assertIn("Nonexistent",result["missing"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
