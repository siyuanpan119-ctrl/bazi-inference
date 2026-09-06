"""Calendar regression tests; does NOT test or endorse life-event inference.

HKO term times are rounded to minutes. Fixtures are independent public
astronomical observations/tables, while the deliberately synthetic day/hour cases check cycle compatibility.
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from calendar_engine import (BRANCHES, STEMS, chart, day_pillar, equation_of_time_minutes,
                             hour_pillar, jie, jdn, month_pillar, resolve_civil,
                             ten_god, branch_relations, solar_term, CalendarBoundaryError)

UTC = timezone.utc
HK = timezone(timedelta(hours=8))
# Source: https://www.hko.gov.hk/sc/gts/astron2013/Solar_Term_2013.htm
HKO_2013 = ((1,5,12,34),(2,4,0,13),(3,5,18,15),(4,4,23,2),(5,5,16,18),(6,5,20,23),
            (7,7,6,35),(8,7,16,20),(9,7,19,16),(10,8,10,58),(11,7,14,14),(12,7,7,9))
# Source: https://www.hko.gov.hk/sc/gts/astron2016/Solar_Term_2016.htm
HKO_2016 = ((1,6,6,8),(2,4,17,46),(3,5,11,44),(4,4,16,28),(5,5,9,42),(6,5,13,49),
            (7,7,0,3),(8,7,9,53),(9,7,12,51),(10,8,4,33),(11,7,7,48),(12,7,0,41))


def make(local, zone="Asia/Hong_Kong", sex="male", **kwargs):
    kwargs.setdefault("time_basis", "civil")
    kwargs.setdefault("day_boundary", "midnight")
    return chart(local, zone, sex, **kwargs)


class DayStemTests(unittest.TestCase):
    def test_gregorian_jdn_external_standard_anchor(self):
        self.assertEqual(jdn(date(2000,1,1)), 2451545)

    def test_synthetic_cycle_dates(self):
        for y,m,d,expected in ((2000,1,7,"甲子"),(2000,1,10,"丁卯"),(2000,1,11,"戊辰")):
            with self.subTest(date=(y,m,d)):
                self.assertEqual(day_pillar(date(y,m,d)),expected)

    def test_leap_day_continuity(self):
        base = date(2000,2,28)
        self.assertEqual(jdn(base+timedelta(days=2))-jdn(base),2)

    def test_hour_boundaries_half_open(self):
        self.assertEqual(hour_pillar("甲",0),"甲子")
        self.assertEqual(hour_pillar("甲",1),"乙丑")
        self.assertEqual(hour_pillar("甲",22),"乙亥")
        self.assertEqual(hour_pillar("甲",23),"甲子")

    def test_all_five_rat_and_tiger_groups(self):
        for stem,rat,tiger in (("甲","甲子","丙寅"),("乙","丙子","戊寅"),
                                ("丙","戊子","庚寅"),("丁","庚子","壬寅"),("戊","壬子","甲寅")):
            self.assertEqual(hour_pillar(stem,0),rat)
            self.assertEqual(month_pillar(stem,0),tiger)

    def test_ten_gods_all_ten_against_jia(self):
        self.assertEqual([ten_god("甲",s) for s in STEMS],
                         ["比肩","劫财","食神","伤官","偏财","正财","七杀","正官","偏印","正印"])

    def test_ten_gods_yin_polarity(self):
        self.assertEqual(ten_god("乙","庚"),"正官")
        self.assertEqual(ten_god("己","丁"),"偏印")
        self.assertEqual(ten_god("丁","庚"),"正财")

    def test_zi23_changes_day_and_hour_stem_together(self):
        a = make("2000-01-10T23:30",day_boundary="midnight")
        b = make("2000-01-10T23:30",day_boundary="zi23")
        self.assertEqual(a["pillars"]["day"],"丁卯")
        self.assertEqual(a["pillars"]["hour"],"庚子")
        self.assertEqual(b["pillars"]["day"],"戊辰")
        self.assertEqual(b["pillars"]["hour"],"壬子")
        c = make("2000-01-11T00:30",day_boundary="midnight")
        self.assertEqual(c["pillars"],b["pillars"])


class TimeTests(unittest.TestCase):
    def test_1990_mainland_dst_correction(self):
        result = resolve_civil("1990-06-12T17:30","Asia/Shanghai")
        self.assertEqual(result["civil"].hour,17)
        self.assertEqual(result["standard"],datetime(1990,6,12,16,30))
        self.assertEqual(result["dst_minutes"],60)
        civil = make("1990-06-12T17:30","Asia/Shanghai")
        std = make("1990-06-12T17:30","Asia/Shanghai",time_basis="standard")
        self.assertEqual(civil["pillars"]["hour"][1],"酉")
        self.assertEqual(std["pillars"]["hour"][1],"申")
        self.assertEqual(civil["time"]["utc"],std["time"]["utc"])

    def test_already_corrected_time_not_double_subtracted(self):
        x = resolve_civil("1990-06-12T16:30","Asia/Shanghai",input_basis="standard")
        y = resolve_civil("1990-06-12T17:30","Asia/Shanghai")
        self.assertEqual(x,y)

    def test_1977_malaysia_two_zones(self):
        west = resolve_civil("1977-11-15T11:10","Asia/Kuala_Lumpur")
        east = resolve_civil("1977-11-15T11:10","Asia/Kuching")
        self.assertEqual(west["offset_minutes"],450)
        self.assertEqual(east["offset_minutes"],480)
        self.assertEqual(west["utc"]-east["utc"],timedelta(minutes=30))

    def test_hong_kong_historical_dst(self):
        # Official HKO Summertime.htm: 1968 starts Apr21; 1973 Apr22; 1980+ none.
        for dt,expected in (("1968-04-12T20:00",0),("1973-06-09T06:00",60),("1981-05-28T02:17",0)):
            with self.subTest(date=dt):
                self.assertEqual(resolve_civil(dt,"Asia/Hong_Kong")["dst_minutes"],expected)

    def test_nonexistent_clock_rejected(self):
        with self.assertRaisesRegex(ValueError,"Nonexistent"):
            resolve_civil("2024-03-10T02:30","America/New_York")

    def test_ambiguous_clock_requires_fold(self):
        with self.assertRaisesRegex(ValueError,"Ambiguous"):
            resolve_civil("2024-11-03T01:30","America/New_York")
        a = resolve_civil("2024-11-03T01:30","America/New_York",fold=0)
        b = resolve_civil("2024-11-03T01:30","America/New_York",fold=1)
        self.assertEqual(b["utc"]-a["utc"],timedelta(hours=1))

    def test_missing_zone_and_solar_longitude_rejected(self):
        with self.assertRaises(ValueError):
            make("1990-06-12T17:30","")
        with self.assertRaises(ValueError):
            make("1990-06-12T17:30",time_basis="apparent_solar")

    def test_conventions_required(self):
        with self.assertRaises(TypeError):
            chart("1990-06-12T17:30","Asia/Shanghai","female")

    def test_apparent_solar_is_same_instant_all_bases(self):
        a = make("1990-06-12T17:30","Asia/Shanghai")
        b = make("1990-06-12T17:30","Asia/Shanghai",time_basis="standard")
        c = make("1990-06-12T17:30","Asia/Shanghai",time_basis="apparent_solar",longitude=116.4)
        self.assertEqual(a["time"]["utc"],b["time"]["utc"])
        self.assertEqual(a["time"]["utc"],c["time"]["utc"])
        for key in ("year","month"):
            self.assertEqual(a["pillars"][key],c["pillars"][key])
        utc = datetime.fromisoformat(c["time"]["utc"])
        expect = utc.replace(tzinfo=None)+timedelta(minutes=4*116.4+equation_of_time_minutes(utc))
        self.assertEqual(c["time"]["selected_clock"],expect.isoformat())

    def test_unknown_city_not_silently_filled(self):
        a = make("2000-05-04T16:40","America/New_York")
        self.assertIsNone(a["input"]["city"])
        self.assertTrue(any("City not supplied" in w for w in a["warnings"]))

    def test_invalid_numeric_inputs_rejected(self):
        for value in (float("nan"),float("inf"),-1,1441):
            with self.subTest(value=value), self.assertRaises(ValueError):
                make("1990-06-12T17:30",time_uncertainty_minutes=value)
        for value in (float("nan"),float("inf"),181):
            with self.subTest(longitude=value), self.assertRaises(ValueError):
                make("1990-06-12T17:30",time_basis="apparent_solar",longitude=value)

    def test_uncertainty_interval_cannot_hide_dst_transition(self):
        with self.assertRaisesRegex(ValueError,"crosses a timezone/DST"):
            make("2024-03-10T01:30","America/New_York",time_uncertainty_minutes=120)

    def test_input_hour_range_crosses_corrected_hour(self):
        # 05:00–07:00 civil DST is 04:00–06:00 standard, includes 寅 and 卯.
        a = make("1973-06-09T06:00",time_basis="standard",time_uncertainty_minutes=60)
        self.assertEqual({x["hour"][1] for x in a["day_hour_candidates"]},{"寅","卯"})


class SolarTests(unittest.TestCase):
    def test_24_independent_hko_term_anchors(self):
        for year,rows in ((2013,HKO_2013),(2016,HKO_2016)):
            for month,day,hour,minute in rows:
                with self.subTest(year=year,month=month):
                    observed = datetime(year,month,day,hour,minute,tzinfo=HK)
                    error_minutes = abs((jie(year,month).utc-observed).total_seconds()/60)
                    self.assertLess(error_minutes,15)

    def test_term_boundary_uncertainty_retains_both_sides(self):
        local = solar_term(2016,2).utc.astimezone(HK).replace(tzinfo=None)
        result = make(local)
        self.assertEqual({x["year"] for x in result["year_month_candidates"]},{"乙未","丙申"})
        self.assertEqual({x["month"] for x in result["year_month_candidates"]},{"己丑","庚寅"})
        self.assertTrue(result["luck"]["uncertain"])

    def test_bundled_hko_is_used_in_real_chart_not_only_tests(self):
        a = make("2016-02-04T18:00")
        self.assertEqual(a["solar_context"]["previous_jie"]["utc"], "2016-02-04T09:46:00+00:00")
        self.assertIn("hko.gov.hk", a["solar_context"]["previous_jie"]["source"])
        self.assertEqual(a["solar_context"]["previous_jie"]["margin_minutes"], 1)

    def test_strict_solar_boundary_rejects_unique_chart(self):
        with self.assertRaises(CalendarBoundaryError) as raised:
            make("2016-02-04T17:46", strict_boundary=True)
        self.assertFalse(raised.exception.result["usable_for_single_chart_interpretation"])
        self.assertEqual(len(raised.exception.result["year_month_candidates"]), 2)

    def test_strict_unknown_year_uses_operational_buffer(self):
        t = jie(2027,2).utc.astimezone(HK).replace(tzinfo=None)
        with self.assertRaises(CalendarBoundaryError):
            make(t, strict_boundary=True)

    def test_strict_clock_range_retains_candidates(self):
        with self.assertRaises(CalendarBoundaryError) as raised:
            make("1990-06-12T17:00", strict_boundary=True, time_uncertainty_minutes=2)
        self.assertGreater(len(raised.exception.result["day_hour_candidates"]), 1)

    def test_verified_override_metadata_and_precise_sides(self):
        overrides = {"2016-立春":{"utc":"2016-02-04T09:46:00+00:00","source":"HKO 2016", "margin_minutes":1}}
        a = make("2016-02-04T17:44",verified_terms=overrides)
        b = make("2016-02-04T17:48",verified_terms=overrides)
        self.assertEqual(a["pillars"]["year"],"乙未")
        self.assertEqual(b["pillars"]["year"],"丙申")
        self.assertFalse(a["year_month_candidates"])
        self.assertTrue(a["precision"]["verified_term_overrides"])

    def test_invalid_override_margin_rejected(self):
        for margin in (-1,float("nan"),float("inf")):
            overrides = {"2016-立春":{"utc":"2016-02-04T09:46:00+00:00","source":"HKO 2016","margin_minutes":margin}}
            with self.subTest(margin=margin), self.assertRaises(ValueError):
                make("2016-02-04T17:44",verified_terms=overrides)

    def test_not_using_lunar_new_year_or_january_first(self):
        self.assertEqual(make("2000-01-26T06:00")["pillars"]["year"],"己卯")

    def test_da_yun_uses_jie_not_zhongqi(self):
        a = make("2000-08-20T02:00")
        self.assertEqual(a["luck"]["direction"],"forward")
        self.assertEqual(a["luck"]["target_jie"],"白露")
        self.assertEqual(a["luck"]["cycles"][0]["pillar"],"乙酉")
        b = make("2000-08-20T02:00",sex="female")
        self.assertEqual(b["luck"]["direction"],"backward")
        self.assertEqual(b["luck"]["target_jie"],"立秋")
        self.assertAlmostEqual(a["luck"]["start_age_years"],a["luck"]["gap_days"]/3,7)

    def test_branch_relations_do_not_assert_transformation(self):
        data = branch_relations(["申","子","辰","酉"])
        self.assertTrue(any(x["kind"] == "三合齐全" for x in data))
        self.assertFalse(any("化水" in str(x) for x in data))


if __name__ == "__main__":
    unittest.main(verbosity=2)
