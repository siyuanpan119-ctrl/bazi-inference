"""Report interfaces, provenance and ambiguity gates; not predictive-validity tests."""
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path

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

    def test_external_scenario_preserves_place_and_provenance(self):
        place = {"status": "scenario", "city": "Paris", "timezone": "Europe/Paris",
                 "timezone_source": "https://data.iana.org/time-zones/tzdb/europe"}
        original = request(birthplace=place)
        before = deepcopy(original)
        result = generate_report(original, as_of="2022-01-01")
        self.assertEqual(original, before)
        self.assertEqual(result["input"], before)
        self.assertEqual(result["status"], "ready_with_limitations")
        for key in ("status", "city", "timezone", "timezone_source"):
            self.assertEqual(result["birthplace_resolution"][key], place[key])
        self.assertTrue(result["interpretation_must_be_conditional_on_birthplace"])
        self.assertIn("非已确认出生城市", result["report_markdown"])
        for override in ({"timezone_source": None}, {"status": "unverified"}):
            incomplete = generate_report(request(birthplace={**place, **override}), as_of="2022-01-01")
            self.assertEqual(incomplete["status"], "needs_resolution")
            self.assertNotIn("chart", incomplete)

    def test_shichen_requires_an_explicit_valid_uncertainty_window(self):
        values = [{}, *({"time_uncertainty_minutes": v} for v in (0, -1, True, None, "60", float("nan"), float("inf")))]
        for value in values:
            with self.subTest(value=value):
                result = generate_report(request(time_precision="shichen", **value), as_of="2022-01-01")
                self.assertEqual(result["status"], "needs_resolution")
                self.assertNotIn("chart", result)
        original = request(birth_datetime="2000-01-01T08:00", time_precision="shichen", time_uncertainty_minutes=60)
        before = deepcopy(original)
        result = generate_report(original, as_of="2022-01-01")
        self.assertEqual(original, before)
        precision = result["birth_time_precision"]
        self.assertTrue(precision["is_representative"])
        self.assertEqual(precision["interval"]["start"], "2000-01-01T07:00:00")
        self.assertEqual(precision["interval"]["end"], "2000-01-01T09:00:00")
        self.assertIn("conservative", precision["interval"]["boundary_policy"])
        self.assertEqual(result["chart"]["input"]["time_uncertainty_minutes"], 60)
        self.assertEqual(result["status"], "needs_verification")
        self.assertEqual(result["annual_reports"], [])
        self.assertIn("端点邻盘不等于真实候选", result["report_markdown"])
        scenario = generate_report({**original, "strict_boundary": False}, as_of="2022-01-01")
        self.assertEqual(scenario["status"], "needs_verification")
        self.assertTrue(scenario["chart"]["nominal_pillars_only"])
        self.assertTrue(scenario["annual_reports"])
        self.assertTrue(scenario["dayun"])
        self.assertEqual(scenario["chart"]["input"]["time_uncertainty_minutes"], 60)
        self.assertGreater(scenario["chart"]["luck"]["age_margin_years_operational"], 0)
        self.assertGreater(scenario["dayun"][0]["start_date_margin_days_operational"], 0)

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
        self.assertEqual(result["observation"]["precision"], "date")
        self.assertTrue(result["observation"]["calculation_anchor"]["is_observation_date"])
        self.assertFalse(result["birth_time_precision"]["is_representative"])
        self.assertIn("资料观察截止：2013-05-06", result["report_markdown"])

    def test_year_only_observation_retains_unknown_date_and_full_coverage(self):
        original = request(observation_year=2013)
        before = deepcopy(original)
        result = generate_report(original)
        self.assertEqual(original, before)
        self.assertEqual(result["input"], before)
        self.assertIsNone(result["as_of"])
        observation = result["observation"]
        self.assertEqual(observation["precision"], "year")
        self.assertIsNone(observation["date"])
        self.assertFalse(observation["calculation_anchor"]["is_observation_date"])
        self.assertEqual(observation["calculation_anchor"]["date"], "2013-07-01")
        self.assertEqual(observation["interval"]["start_inclusive"], "2013-01-01")
        self.assertEqual(observation["interval"]["end_exclusive"], "2014-01-01")
        self.assertEqual(observation["interval"]["start_utc"], "2012-12-31T16:00:00+00:00")
        self.assertEqual([a["solar_year"] for a in result["annual_reports"]], [2012, 2013])
        self.assertNotIn("资料观察截止", result["report_markdown"])
        self.assertIn("非真实观察日期", result["report_markdown"])
        with self.assertRaisesRegex(ValueError, "either as_of or observation_year"):
            generate_report(original, as_of="2013-12-31")

    def test_year_only_keeps_luck_transition_even_with_additional_report_years(self):
        initial = generate_report(request(), as_of="2040-01-01")
        switch = datetime.fromisoformat(initial["dayun"][2]["start_utc_approx"])
        result = generate_report(request(observation_year=switch.year), years=[switch.year+1])
        self.assertEqual([a["solar_year"] for a in result["annual_reports"]], [switch.year-1, switch.year, switch.year+1])
        segments = result["observation"]["dayun_segments"]
        self.assertEqual({s["sequence"] for s in segments}, {2, 3})
        self.assertEqual(segments[0]["overlap_end_utc_approx"], switch.isoformat())
        self.assertEqual(segments[1]["overlap_start_utc_approx"], switch.isoformat())

    def test_year_only_birth_year_and_supported_range_are_explicit(self):
        result = generate_report(request(birth_datetime="2000-08-01T12:30", observation_year=2000))
        self.assertEqual(result["observation"]["coverage"], "partial_birth_year")
        self.assertEqual(result["observation"]["pre_birth_solar_years"], [1999])
        self.assertEqual([a["solar_year"] for a in result["annual_reports"]], [2000])
        for value in (1900, 2101, True, "2013"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "observation_year must"):
                generate_report(request(observation_year=value))
        with self.assertRaisesRegex(ValueError, "after observation_year"):
            generate_report(request(observation_year=1999))

    def test_year_coverage_preserves_birth_window_crossing_new_year(self):
        for strict in (True, False):
            for birth, nominal in (("1999-12-31T23:30", "complete_year"),
                                   ("2000-01-01T00:30", "partial_birth_year")):
                with self.subTest(strict=strict, birth=birth):
                    result = generate_report(request(birth_datetime=birth, observation_year=2000,
                                                     time_uncertainty_minutes=60, strict_boundary=strict))
                    observation = result["observation"]
                    self.assertEqual(observation["coverage"], "uncertain_birth_year_boundary")
                    self.assertEqual(observation["nominal_coverage"], nominal)
                    self.assertEqual(observation["coverage_candidates"], ["complete_year", "partial_birth_year"])
                    self.assertEqual(result["status"], "needs_verification")
                    self.assertEqual(bool(result["annual_reports"]), not strict)
            for birth, uncertainty, expected in (("1999-12-31T23:00", 60, "complete_year"),
                                                 ("2000-01-01T01:00", 60, "uncertain_birth_year_boundary"),
                                                 ("2000-01-01T00:00", 0, "complete_year")):
                with self.subTest(strict=strict, endpoint_birth=birth):
                    result = generate_report(request(birth_datetime=birth, observation_year=2000,
                                                     time_uncertainty_minutes=uncertainty, strict_boundary=strict))
                    self.assertEqual(result["observation"]["coverage"], expected)

    def test_cli_accepts_year_only_observation(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([sys.executable, str(root/"scripts/report_engine.py"),
                                 "--input", str(root/"assets/birth-input.example.json"), "--as-of-year", "2013", "--year", "2013"],
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertIsNone(report["as_of"])
        self.assertEqual(report["input"]["observation_year"], 2013)
        self.assertEqual([a["solar_year"] for a in report["annual_reports"]], [2012, 2013])

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
        for time in ("17:45", "17:46"):
            year_only = generate_report(request(birth_datetime=f"2016-02-04T{time}", observation_year=2026))
            observation = year_only["observation"]
            self.assertEqual(observation["dayun_segments_status"], "withheld_birth_boundary")
            self.assertEqual(observation["dayun_segments"], [])
            for key in ("contains_pre_dayun_time", "extends_beyond_generated_dayun", "pre_birth_solar_years"):
                self.assertIsNone(observation[key])

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
