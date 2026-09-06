"""Offline birth-chart, Da-Yun and annual-report facts for a host AI.

No network calls; never selects life events or treats traditional themes as facts.
User supplies birth datetime, sex and city. The host supplies explicit as_of.
"""
from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from calendar_engine import (BRANCHES, STEMS, ELEMENTS, HIDDEN, UTC, chart,
                             branch_relations, month_pillar, solar_term,
                             ten_god, year_pillar)

VERSION = "1.0.0"
IANA_ZONE_SOURCE = "https://data.iana.org/time-zones/tzdb/zone.tab"
IANA_ASIA_SOURCE = "https://data.iana.org/time-zones/tzdb/asia"

# Longitude is the tzdb principal-location coordinate, NOT a hospital coordinate.
# Other listed cities resolve their clock zone only; no invented coordinates.
CITY_CONFIGS = (
    ("香港", "Asia/Hong_Kong", 114.15, ("香港", "中国香港", "中國香港", "Hong Kong", "Hong Kong SAR")),
    ("台北", "Asia/Taipei", 121.5, ("台北", "臺北", "台北市", "臺北市", "Taipei")),
    ("上海", "Asia/Shanghai", 121.4666666667, ("上海", "上海市", "Shanghai")),
    ("北京", "Asia/Shanghai", None, ("北京", "北京市", "Beijing", "Peking")),
    ("广州", "Asia/Shanghai", None, ("广州", "廣州", "广州市", "Guangzhou")),
    ("深圳", "Asia/Shanghai", None, ("深圳", "深圳市", "Shenzhen")),
    ("唐山", "Asia/Shanghai", None, ("唐山", "唐山市", "Tangshan")),
    ("吉隆坡", "Asia/Kuala_Lumpur", 101.7, ("吉隆坡", "Kuala Lumpur")),
    ("乔治市", "Asia/Kuala_Lumpur", None, ("乔治市", "喬治市", "槟城乔治市", "George Town, Penang", "George Town Penang")),
    ("新山", "Asia/Kuala_Lumpur", None, ("新山", "Johor Bahru")),
    ("怡保", "Asia/Kuala_Lumpur", None, ("怡保", "Ipoh")),
    ("古晋", "Asia/Kuching", 110.3333333333, ("古晋", "古晉", "Kuching")),
    ("亚庇", "Asia/Kuching", None, ("亚庇", "亞庇", "Kota Kinabalu")),
)


def _normal_city(value: str) -> str:
    return "".join(value.casefold().split())


def resolve_birthplace(value: str | dict, birth_year: int) -> dict:
    """Small reviewed gazetteer; unknown locations require host resolution.

    An externally resolved object needs city/timezone/timezone_source. The source
    is an auditable assertion by the caller; this program does not verify URLs.
    """
    if isinstance(value, dict):
        if not all(value.get(k) for k in ("city", "timezone", "timezone_source")):
            return {"status": "needs_resolution", "missing": ["city, timezone and timezone_source for external place resolution"]}
        if value.get("longitude_east") is not None:
            x = value["longitude_east"]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not -180 <= x <= 180:
                raise ValueError("longitude_east must be finite and between -180 and 180")
            if not value.get("longitude_source"):
                return {"status": "needs_resolution", "missing": ["longitude_source"]}
        return {"status": "resolved", "city": value["city"], "timezone": value["timezone"],
                "timezone_source": value["timezone_source"], "resolution": "caller_asserted_with_source",
                "longitude_east": value.get("longitude_east"), "longitude_source": value.get("longitude_source"),
                "longitude_precision": value.get("longitude_precision", "caller must state geographic precision")}
    if not isinstance(value, str) or not value.strip():
        return {"status": "needs_resolution", "missing": ["birthplace city"]}
    key = _normal_city(value)
    for name, zone, longitude, aliases in CITY_CONFIGS:
        if key in {_normal_city(x) for x in aliases}:
            # Since 1970 merged tzdb zones are not a historical atlas of all cities.
            if birth_year < 1970 and zone == "Asia/Shanghai" and name != "上海":
                return {"status": "needs_resolution", "city": name,
                        "missing": ["historical local timezone verification before 1970; city must not inherit Shanghai's early history"]}
            return {"status": "resolved", "city": name, "timezone": zone,
                    "timezone_source": IANA_ZONE_SOURCE, "historical_zone_source": IANA_ASIA_SOURCE,
                    "resolution": "reviewed_city_alias", "longitude_east": longitude,
                    "longitude_source": IANA_ZONE_SOURCE if longitude is not None else None,
                    "longitude_precision": "tzdb principal-location coordinate; city reference only" if longitude is not None else None}
    return {"status": "needs_resolution", "original": value,
            "missing": ["unambiguous city and historical clock zone; do not substitute a capital for a country"]}


def stem_relations(stems: list[str]) -> list[dict]:
    """Directed element production/control and five stem pairs, no 合化 claim."""
    result = []
    combines = ("甲己", "乙庚", "丙辛", "丁壬", "戊癸")
    for i, a in enumerate(stems):
        if a not in STEMS:
            raise ValueError("Invalid stem")
        for j in range(i + 1, len(stems)):
            b = stems[j]
            if b not in STEMS:
                raise ValueError("Invalid stem")
            if any({a, b} == set(pair) for pair in combines):
                result.append({"kind": "天干五合配对", "positions": [i,j], "stems": a+b, "transformation_claimed": False})
            ea, eb = STEMS.index(a)//2, STEMS.index(b)//2
            if ea == eb:
                result.append({"kind": "同五行", "positions": [i,j], "stems": a+b})
            else:
                for first, second, efirst, esecond in ((i,j,ea,eb),(j,i,eb,ea)):
                    relation = (esecond-efirst) % 5
                    if relation in (1,2):
                        result.append({"kind": "生" if relation == 1 else "克", "positions": [first,second], "stems": stems[first]+stems[second]})
    return result


def pillar_relations(pillars: list[str], labels: list[str]) -> dict:
    def label(records: list[dict]) -> list[dict]:
        return [{**r, "labels": [labels[x] for x in r["positions"]]} for r in records]
    return {"stems": label(stem_relations([p[0] for p in pillars])),
            "branches": label(branch_relations([p[1] for p in pillars])),
            "interpretation": "syntactic relations only; no automatic transformation, outcome or severity"}


def _term_data(term) -> dict:
    return {"name": term.name, "utc": term.utc.isoformat(), "source": term.source,
            "margin_minutes_operational": term.margin_minutes,
            "margin_is_proven_error_bound": False}


def luck_intervals(calculation: dict) -> list[dict]:
    """Nine ten-year cycles, using the chart's declared elapsed-time convention."""
    first_start = datetime.fromisoformat(calculation["luck"]["start_utc_approx"])
    ten_years = timedelta(days=10*365.2425)
    margin_days = calculation["luck"]["age_margin_years_operational"] * 365.2425
    result = []
    for n, entry in enumerate(calculation["luck"]["cycles"], 1):
        start = first_start + (n-1)*ten_years
        end = start + ten_years
        result.append({"sequence": n, "pillar": entry["pillar"],
                       "stem_ten_god": ten_god(calculation["pillars"]["day"][0], entry["pillar"][0]),
                       "start_age_years": entry["start_age_years"], "end_age_years": entry["start_age_years"]+10,
                       "start_utc_approx": start.isoformat(), "end_utc_approx": end.isoformat(),
                       "start_date_margin_days_operational": margin_days,
                       "end_date_margin_days_operational": margin_days,
                       "date_margin_is_proven_error_bound": False,
                       "interval_convention": "[start,end); elapsed-year conversion; not a universally fixed civil anniversary"})
    return result


def _overlapping_luck_segments(cycles: list[dict], start: datetime, end: datetime,
                              birth: datetime, natal: list[str], labels: list[str],
                              added_pillars: list[str], added_labels: list[str]) -> list[dict]:
    """Shared annual/monthly overlap logic with operational boundary margins."""
    if end <= birth:
        return []
    segments = []
    for c in cycles:
        lo, hi = datetime.fromisoformat(c["start_utc_approx"]), datetime.fromisoformat(c["end_utc_approx"])
        margin = timedelta(days=c["start_date_margin_days_operational"])
        if lo-margin < end and hi+margin > max(start,birth):
            nominal_lo, nominal_hi = max(lo,start,birth), min(hi,end)
            overlap_only_in_margin = nominal_lo >= nominal_hi
            segments.append({"sequence": c["sequence"], "pillar": c["pillar"],
                             "overlap_start_utc_approx": nominal_lo.isoformat() if not overlap_only_in_margin else None,
                             "overlap_end_utc_approx": nominal_hi.isoformat() if not overlap_only_in_margin else None,
                             "possible_only_within_start_date_margin": overlap_only_in_margin,
                             "luck_start_date_margin_days_operational": c["start_date_margin_days_operational"],
                             "relations": pillar_relations(natal+[c["pillar"]]+added_pillars, labels+["大运"]+added_labels)})
    return segments


def annual_facts(calculation: dict, year: int, cycles: list[dict], *, verified_terms: dict | None = None) -> dict:
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100:
        raise ValueError("Annual solar year must be an integer in 1900–2100")
    birth_utc = datetime.fromisoformat(calculation["time"]["utc"])
    start, end = solar_term(year, 2, verified_terms), solar_term(year+1, 2, verified_terms)
    if end.utc <= birth_utc:
        raise ValueError("Requested annual interval ends before birth")
    natal = list(calculation["pillars"].values())
    labels = ["年柱", "月柱", "日柱", "时柱"]
    pillar = year_pillar(year)
    god = ten_god(natal[2][0], pillar[0])
    segments = _overlapping_luck_segments(cycles,start.utc,end.utc,birth_utc,natal,labels,[pillar],["流年"])
    months = []
    for order in range(12):
        civil_month = (order+1) % 12 + 1  # Feb ... Dec, Jan next year
        civil_year = year if civil_month >= 2 else year+1
        term = solar_term(civil_year, civil_month, verified_terms)
        following_month = civil_month % 12 + 1
        following_year = civil_year + int(following_month == 1)
        next_term = solar_term(following_year, following_month, verified_terms)
        mp = month_pillar(pillar[0], order)
        months.append({"order": order, "pillar": mp, "stem_ten_god": ten_god(natal[2][0],mp[0]),
                       "starts_at_jie": _term_data(term), "ends_at_jie": _term_data(next_term),
                       "relations": pillar_relations(natal+[pillar,mp],labels+["流年","流月"]),
                       "dayun_segments": _overlapping_luck_segments(cycles,term.utc,next_term.utc,birth_utc,
                                                                    natal,labels,[pillar,mp],["流年","流月"])})
    themes = {
        "比肩": "自主安排、同辈协作与资源分配", "劫财": "合作边界、竞争及共同支出",
        "食神": "表达、技能输出和生活节奏", "伤官": "表达方式、创新和制度要求的协调",
        "偏财": "项目资源、交易机会及不固定收入", "正财": "日常收入、支出与资源管理",
        "七杀": "压力、职责要求与应对能力", "正官": "职责、组织规则与承诺",
        "偏印": "研究、学习方式与支持资源", "正印": "学习、支持和制度内资源",
    }
    pre_luck = bool(cycles and start.utc < datetime.fromisoformat(cycles[0]["start_utc_approx"]))
    return {"solar_year": year, "pillar": pillar, "stem_ten_god": god,
            "interval": {"start": _term_data(start), "end": _term_data(end), "convention": "[立春, next 立春); not Gregorian January–December"},
            "annual_natal_relations": pillar_relations(natal+[pillar],labels+["流年"]),
            "dayun_segments": segments, "contains_pre_dayun_time": pre_luck,
            "outside_generated_dayun_range": not segments and not pre_luck,
            "birth_falls_within_annual_interval": start.utc <= birth_utc < end.utc,
            "months": months,
            "traditional_observation": {
                "claim_status": "traditional_hypothesis_not_empirical_prediction",
                "basis": f"流年天干{pillar[0]}相对日主{natal[2][0]}为{god}",
                "theme": themes[god],
                "text": f"按十神传统语义，本年可把{themes[god]}列作观察主题。是否有利，仍须先核定月令格局、扶抑与调候条件，以及大运配合；这里不据此断定得财、升职或具体事故。",
            },
            "interpretation_tasks": [
                "Read interpretation protocol; determine 格局用神 and 相神 separately from 扶抑/调候 preferences.",
                "Assess natal seasonal context and roots before assigning benefit/harm; do not use element counts as strength scores.",
                "Interpret each overlapping Da-Yun segment and preserve its transition uncertainty.",
                "For each event candidate, list subject, action, period, source, alternative and disconfirming condition.",
                "Do not infer medical diagnosis, sexual orientation, criminal history or death from branch relations.",
            ]}


def generate_report(request: dict, *, as_of: str, years: list[int] | None = None) -> dict:
    """Generate calculation facts and a usable report scaffold; do not mutate input."""
    req = deepcopy(request)
    if not isinstance(req, dict):
        raise ValueError("Birth request must be a JSON object")
    if not as_of:
        raise ValueError("as_of is required from host context; never freeze 'now' in code")
    observation_date = date.fromisoformat(as_of)
    output = {"schema_version": VERSION, "as_of": observation_date.isoformat(),
              "synthetic": req.get("synthetic", False), "input": req,
              "calculation_and_interpretation_are_separate": True}
    missing = [k for k in ("birth_datetime", "sex", "birthplace") if not req.get(k)]
    if missing:
        return {**output, "status": "needs_resolution", "missing": missing}
    if req.get("calendar", "gregorian") not in ("gregorian", "solar", "公历", "西历", "西曆"):
        return {**output, "status": "needs_resolution", "missing": ["verified Gregorian conversion including lunar leap-month status"]}
    if not isinstance(req["birth_datetime"], str) or not any(mark in req["birth_datetime"] for mark in ("T", " ")):
        return {**output, "status": "needs_resolution", "missing": ["birth clock time; a date alone must not default to midnight"]}
    sex = {"男":"male", "男命":"male", "女":"female", "女命":"female", "male":"male", "female":"female"}.get(req["sex"])
    if sex is None:
        raise ValueError("sex must be male/female/男/女 for the stated traditional direction convention")
    local = datetime.fromisoformat(req["birth_datetime"])
    if local.tzinfo is not None:
        raise ValueError("birth_datetime is local wall-clock time without offset; city resolves its historical offset")
    if local.date() > observation_date:
        raise ValueError("Birth date is after as_of")
    place_value = req["birthplace"]
    if isinstance(place_value, str) and req.get("timezone"):
        place_value = {"city": req.get("city", place_value), "timezone": req["timezone"],
                       "timezone_source": req.get("timezone_source"), "longitude_east": req.get("longitude_east"),
                       "longitude_source": req.get("longitude_source")}
    place = resolve_birthplace(place_value, local.year)
    output["birthplace_resolution"] = place
    if place["status"] != "resolved":
        return {**output, "status": "needs_resolution", "missing": place["missing"]}
    basis = req.get("time_basis", "standard")
    day_boundary = req.get("day_boundary", "midnight")
    common = {"city": place["city"], "input_basis": req.get("input_basis", "civil"),
              "day_boundary": day_boundary, "longitude": place.get("longitude_east"),
              "fold": req.get("fold"), "time_uncertainty_minutes": req.get("time_uncertainty_minutes", 0),
              "verified_terms": req.get("verified_terms")}
    try:
        calculation = chart(local, place["timezone"], sex, time_basis=basis, **common)
    except (ValueError, KeyError) as exc:
        return {**output, "status": "needs_resolution", "missing": [str(exc)]}
    output["conventions"] = {"input_basis": common["input_basis"], "time_basis": basis,
                             "day_boundary": day_boundary, "strict_boundary": req.get("strict_boundary", True),
                             "time_basis_default_is_declared_convention": "standard removes historical DST; other schools can select a named alternative"}
    output["chart"] = calculation
    alternatives = []
    for alternative in ("civil", "standard", "apparent_solar"):
        if alternative == basis:
            continue
        if alternative == "apparent_solar" and common["longitude"] is None:
            alternatives.append({"time_basis": alternative, "status": "needs_longitude", "changes_pillars": None})
            continue
        scenario = chart(local, place["timezone"], sex, time_basis=alternative, **common)
        alternatives.append({"time_basis": alternative, "status": "scenario", "pillars": scenario["pillars"],
                             "changes_pillars": scenario["pillars"] != calculation["pillars"],
                             "selected_clock": scenario["time"]["selected_clock"],
                             "day_hour_candidates": scenario["day_hour_candidates"],
                             "longitude_precision": place.get("longitude_precision") if alternative == "apparent_solar" else None,
                             "usable_for_single_chart_interpretation": scenario["usable_for_single_chart_interpretation"]})
    output["time_basis_alternatives"] = alternatives
    output["day_boundary_alternative"] = None
    hour = datetime.fromisoformat(calculation["time"]["selected_clock"]).hour
    if hour == 23:
        alternate_common = {**common, "day_boundary": "zi23" if day_boundary == "midnight" else "midnight"}
        other = chart(local, place["timezone"], sex, time_basis=basis, **alternate_common)
        output["day_boundary_alternative"] = {"day_boundary": alternate_common["day_boundary"], "pillars": other["pillars"]}
    output["interpretation_must_be_conditional_on_time_convention"] = bool(
        any(a.get("changes_pillars") for a in alternatives) or output["day_boundary_alternative"])
    unresolved = not calculation["usable_for_single_chart_interpretation"]
    output["status"] = "needs_verification" if unresolved else "ready_with_limitations"
    output["dayun"] = luck_intervals(calculation)
    requested_years = years if years is not None else req.get("years", [observation_date.year])
    if not isinstance(requested_years, list) or not requested_years:
        raise ValueError("years must be a nonempty list")
    if len(requested_years) > 100:
        raise ValueError("At most 100 requested annual intervals per report")
    # Strict mode permits an auditable candidate chart but withholds interpretation
    # material that could quietly turn a nominal boundary choice into an answer.
    if unresolved and req.get("strict_boundary", True):
        output["chart"]["nominal_pillars_only"] = True
        output["annual_reports"] = []
        output["withheld_reason"] = "Resolve birth solar-term/hour/day candidates before a single-chart annual reading; nominal Da-Yun must also be recomputed."
        output["dayun"] = []
    else:
        output["annual_reports"] = [annual_facts(calculation, y, output["dayun"], verified_terms=req.get("verified_terms"))
                                    for y in sorted(set(requested_years))]
    output["report_outline"] = [
        {"section": "出生资料与计算口径", "source": "input, birthplace_resolution, conventions, time_basis_alternatives"},
        {"section": "四柱、月令与十神", "source": "chart.pillars, chart.hidden_stems, chart.stem_ten_gods"},
        {"section": "格局与扶抑、调候分析", "source": "host AI analysis under references/inference.md; label hypotheses separately"},
        {"section": "大运阶段", "source": "dayun; retain start-date uncertainty and boundary scenarios"},
        {"section": "年度及月度观察", "source": "annual_reports; actual months are Jie intervals"},
        {"section": "主要判断的依据与适用条件", "source": "explain the natal-to-luck causal hypothesis, competing interpretation and scope; avoid unsupported event probabilities"},
    ]
    output["limitations"] = [
        "Calculation agreement verifies implementation, not the predictive validity of traditional BaZi.",
        "Bundled HKO 2013/2016 minute tables take precedence over pinned Astronomy Engine; the 30-minute operational boundary buffer is not a proven accuracy bound. Raw backend validation at 24 HKO terms is not universal minute precision.",
        "Historical timezone information follows the installed IANA tzdb; unusual local clock practices need documentary verification.",
        "Apparent solar alternatives use a city reference longitude where available, not a precisely verified birthplace coordinate.",
        "Specific diagnoses, legal events, bereavement, wealth amounts and relationship facts are not generated by this engine.",
    ]
    output["report_markdown"] = render_markdown(output)
    return output


def render_markdown(report: dict) -> str:
    lines = ["# 八字与流年分析工作底稿", "", f"资料观察截止：{report['as_of']}。计算状态：{report['status']}。", ""]
    if report.get("synthetic"):
        lines += ["这是明确标记的合成输入，用于演示接口，不对应真实命主。", ""]
    calculation = report["chart"]
    p = calculation["pillars"]
    lines += [f"四柱计算：{p['year']}　{p['month']}　{p['day']}　{p['hour']}。",
              f"口径：{report['conventions']['time_basis']}，换日：{report['conventions']['day_boundary']}。", ""]
    if report["status"] == "needs_verification":
        lines += ["出生靠近计算边界，以上只是名义候选；核实时刻与候选盘后才能开展唯一命盘分析。", ""]
    if report.get("interpretation_must_be_conditional_on_time_convention"):
        lines += ["民用时、标准时、太阳时或换日约定会改变部分四柱；解读必须注明所选口径，并检查结论是否随之改变。", ""]
    if report["dayun"]:
        lines += ["| 大运 | 起运周岁约数 | 起止UTC约值 |", "|---|---:|---|"]
        for c in report["dayun"]:
            lines.append(f"| {c['pillar']} | {c['start_age_years']:.2f} | {c['start_utc_approx'][:10]}—{c['end_utc_approx'][:10]} |")
        lines += ["", "起运日期由三天折一年及365.2425日折周年换算；这些日期有节气与输入误差，不能视为公认精确交运日。", ""]
    for a in report["annual_reports"]:
        lines += [f"## {a['solar_year']}年 {a['pillar']}", "", a["traditional_observation"]["text"], "",
                  "| 节月 | 月柱 | 天干十神 | 起始UTC约值 |", "|---|---|---|---|"]
        for m in a["months"]:
            lines.append(f"| {m['starts_at_jie']['name']} | {m['pillar']} | {m['stem_ten_god']} | {m['starts_at_jie']['utc'][:16]} |")
        lines += ["", "原局格局、岁运喜忌和生活背景仍须由调用本技能的AI按解释规程完成；以上主题不是已经验证的个人事件预测。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--as-of", required=True, help="Explicit YYYY-MM-DD from the user's observation date or host context")
    parser.add_argument("--year", action="append", type=int, dest="years")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        result = generate_report(json.loads(args.input.read_text(encoding="utf-8")), as_of=args.as_of, years=args.years)
    except (ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Invalid input: {exc}\n")
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(result.get("report_markdown", json.dumps(result, ensure_ascii=False, indent=2)), encoding="utf-8")


if __name__ == "__main__":
    main()
