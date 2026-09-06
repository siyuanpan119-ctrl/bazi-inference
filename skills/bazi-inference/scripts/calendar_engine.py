"""Auditable calendrical calculations; no life-event prediction.

Python 3.10+, standard library plus pinned MIT Astronomy Engine source.
HKO minute tables take precedence; see references/calculation.md for limits.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo
from vendor import astronomy

UTC = timezone.utc
STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ELEMENTS = "木火土金水"  # generation order
HIDDEN = dict(zip(BRANCHES, ("癸", "己癸辛", "甲丙戊", "乙", "戊乙癸", "丙戊庚", "丁己", "己丁乙", "庚壬戊", "辛", "戊辛丁", "壬甲")))
JIE_NAMES = ("小寒", "立春", "惊蛰", "清明", "立夏", "芒种", "小暑", "立秋", "白露", "寒露", "立冬", "大雪")
SOLAR_MARGIN_MINUTES = 30.0  # operational buffer, not an error theorem
EOT_MARGIN_SECONDS = 60.0
MODEL_VERSION = "bazi-calendar-v1.2-hko-astronomy-engine"
EPHEMERIS_COMMIT = "826e26ff3a6dc03ee46658b1138fef582d96c5d9"
EPHEMERIS_SOURCE = f"https://github.com/cosinekitty/astronomy/tree/{EPHEMERIS_COMMIT}"

# Public astronomical facts, verified against HKO's minute-resolution tables.
# These improve the covered years only; they do NOT calibrate the other years.
HKO_JIE_FIXTURES = {
    2013: ((1,5,12,34),(2,4,0,13),(3,5,18,15),(4,4,23,2),(5,5,16,18),(6,5,20,23),
           (7,7,6,35),(8,7,16,20),(9,7,19,16),(10,8,10,58),(11,7,14,14),(12,7,7,9)),
    2016: ((1,6,6,8),(2,4,17,46),(3,5,11,44),(4,4,16,28),(5,5,9,42),(6,5,13,49),
           (7,7,0,3),(8,7,9,53),(9,7,12,51),(10,8,4,33),(11,7,7,48),(12,7,0,41)),
}


class CalendarBoundaryError(ValueError):
    """Strict mode must not emit a single definitive chart at a boundary."""
    def __init__(self, result: dict):
        super().__init__("Unresolved solar-term or hour/day boundary; inspect candidates and improve input precision")
        self.result = result


def tzdata_version() -> str:
    from zoneinfo import TZPATH
    for folder in TZPATH:
        candidate = Path(folder) / "tzdata.zi"
        if candidate.is_file():
            with candidate.open(encoding="utf-8") as stream:
                return stream.readline().strip()
    try:
        from importlib.metadata import version
        return "tzdata package " + version("tzdata")
    except Exception:
        return "unknown; preserve runtime tzdata for reproducibility"


def jdn(day: date) -> int:
    """Proleptic Gregorian integer JDN at noon (NOT midnight Julian Date)."""
    a = (14 - day.month) // 12
    y = day.year + 4800 - a
    m = day.month + 12 * a - 3
    return day.day + (153 * m + 2) // 5 + 365*y + y//4 - y//100 + y//400 - 32045


def ganzhi(index: int) -> str:
    return STEMS[index % 10] + BRANCHES[index % 12]


def cycle_index(pillar: str) -> int:
    for i in range(60):
        if ganzhi(i) == pillar:
            return i
    raise ValueError(f"Not a sexagenary pillar: {pillar}")


def day_pillar(day: date) -> str:
    return ganzhi((jdn(day) + 49) % 60)


def year_pillar(solar_year: int) -> str:
    """Argument is the Li-Chun year, NOT necessarily civil/lunar birth year."""
    return ganzhi(solar_year - 4)


def month_pillar(year_stem: str, month_order: int) -> str:
    """month_order 0=寅, ... 11=丑; 五虎遁."""
    if year_stem not in STEMS or not 0 <= month_order <= 11:
        raise ValueError("Invalid year stem or month order")
    stem = (STEMS.index(year_stem) % 5 * 2 + 2 + month_order) % 10
    return STEMS[stem] + BRANCHES[(month_order + 2) % 12]


def hour_pillar(day_stem: str, hour: int) -> str:
    """Day stem must already reflect the explicitly selected day boundary."""
    if day_stem not in STEMS or not 0 <= hour <= 23:
        raise ValueError("Invalid day stem or hour")
    branch = ((hour + 1) // 2) % 12
    return STEMS[(STEMS.index(day_stem) % 5 * 2 + branch) % 10] + BRANCHES[branch]


def ten_god(day_stem: str, other_stem: str) -> str:
    a, b = STEMS.index(day_stem), STEMS.index(other_stem)
    relation = (b // 2 - a // 2) % 5
    same_polarity = a % 2 == b % 2
    return {
        0: ("比肩", "劫财"), 1: ("食神", "伤官"),
        2: ("偏财", "正财"), 3: ("七杀", "正官"),
        4: ("偏印", "正印"),
    }[relation][0 if same_polarity else 1]


def _jd_utc(instant: datetime) -> float:
    if instant.tzinfo is None:
        raise ValueError("An aware instant is required")
    u = instant.astimezone(UTC)
    return jdn(u.date()) - 0.5 + (u.hour*3600 + u.minute*60 + u.second + u.microsecond/1e6) / 86400


def _solar_components(instant: datetime) -> tuple[float, float, float, float, float]:
    t = (_jd_utc(instant) - 2451545.0) / 36525
    l0 = (280.46646 + t*(36000.76983 + t*0.0003032)) % 360
    anomaly = 357.52911 + t*(35999.05029 - 0.0001537*t)
    ecc = 0.016708634 - t*(0.000042037 + 0.0000001267*t)
    omega = 125.04 - 1934.136*t
    seconds = 21.448 - t*(46.815 + t*(0.00059 - t*0.001813))
    epsilon = 23 + (26 + seconds/60)/60 + 0.00256*math.cos(math.radians(omega))
    return t, l0, anomaly, ecc, epsilon


def solar_longitude(instant: datetime) -> float:
    """Approximate geocentric apparent tropical longitude, degrees.

    Uses UTC as a UT-like time argument; no explicit TT/UT1 or full nutation
    model. This is intentionally exposed in metadata and the boundary buffer.
    """
    t, l0, anomaly, _, _ = _solar_components(instant)
    m = math.radians(anomaly)
    c = math.sin(m)*(1.914602-t*(0.004817+0.000014*t))
    c += math.sin(2*m)*(0.019993-0.000101*t) + math.sin(3*m)*0.000289
    omega = math.radians(125.04-1934.136*t)
    return (l0 + c - 0.00569 - 0.00478*math.sin(omega)) % 360


def equation_of_time_minutes(instant: datetime) -> float:
    """Apparent solar time MINUS mean solar time; east longitude positive."""
    _, l0, anomaly, ecc, epsilon = _solar_components(instant)
    y = math.tan(math.radians(epsilon)/2)**2
    l, m = math.radians(l0), math.radians(anomaly)
    e = y*math.sin(2*l)-2*ecc*math.sin(m)+4*ecc*y*math.sin(m)*math.cos(2*l)
    e -= 0.5*y*y*math.sin(4*l) + 1.25*ecc*ecc*math.sin(2*m)
    return 4*math.degrees(e)


@dataclass(frozen=True)
class SolarTerm:
    name: str
    utc: datetime
    month_order: int
    longitude: int
    margin_minutes: float = SOLAR_MARGIN_MINUTES
    source: str = "Meeus/NOAA-style truncated solar model; approximate"


@lru_cache(maxsize=4096)
def jie_approx(year: int, civil_month: int) -> SolarTerm:
    """Only the 12 节, not the 12 中气. Root solve to <0.1 s numerically.

    Numerical resolution does NOT imply physical accuracy of 0.1 seconds.
    """
    if not 1899 <= year <= 2101 or not 1 <= civil_month <= 12:
        raise ValueError("Solar-model support is 1900–2100, plus adjacent boundary years")
    angle = (285 + 30*(civil_month-1)) % 360
    left = datetime(year, civil_month, 1, tzinfo=UTC)
    right = left + timedelta(days=11)
    def residual(dt: datetime) -> float:
        return (solar_longitude(dt) - angle + 180) % 360 - 180
    if not residual(left) < 0 < residual(right):
        raise ArithmeticError("Solar term root is not bracketed")
    for _ in range(25):
        middle = left + (right-left)/2
        if residual(middle) < 0:
            left = middle
        else:
            right = middle
    return SolarTerm(JIE_NAMES[civil_month-1], left+(right-left)/2, (civil_month-2)%12, angle)


@lru_cache(maxsize=4096)
def jie(year: int, civil_month: int) -> SolarTerm:
    """Raw pinned Astronomy Engine result, deliberately before HKO overrides.

    The upstream general angular target and numerical root tolerance do not
    establish a universal UTC timing error bound. Retain the operational buffer.
    No silent fallback: failure must be investigated, not hidden by changing model.
    """
    if not 1899 <= year <= 2101 or not 1 <= civil_month <= 12:
        raise ValueError("Calendar support is 1900–2100, plus adjacent boundary years")
    angle = (285 + 30*(civil_month-1)) % 360
    found = astronomy.SearchSunLongitude(angle, astronomy.Time.Make(year,civil_month,1,0,0,0), 10.0)
    if found is None:
        raise ArithmeticError("Astronomy Engine did not bracket the requested Jie")
    instant = found.Utc()
    if instant.tzinfo is None:
        raise ArithmeticError("Astronomy Engine returned a naive UTC timestamp")
    return SolarTerm(JIE_NAMES[civil_month-1], instant.astimezone(UTC), (civil_month-2)%12,
                     angle, SOLAR_MARGIN_MINUTES, EPHEMERIS_SOURCE)


def solar_term(year: int, civil_month: int, verified_terms: dict | None = None) -> SolarTerm:
    """Explicit sourced override > bundled HKO facts > pinned astronomy backend.

    Override keys are YYYY-节名, with utc, source and margin_minutes. Callers
    must verify that a cited source actually contains the supplied timestamp.
    Merely labeling an input 'verified' does not establish its provenance.
    """
    term = jie(year, civil_month)
    if year in HKO_JIE_FIXTURES:
        month, day, hour, minute = HKO_JIE_FIXTURES[year][civil_month-1]
        instant = datetime(year, month, day, hour, minute,
                           tzinfo=timezone(timedelta(hours=8))).astimezone(UTC)
        term = SolarTerm(term.name, instant, term.month_order, term.longitude, 1.0,
                         f"https://www.hko.gov.hk/sc/gts/astron{year}/Solar_Term_{year}.htm")
    key = f"{year}-{term.name}"
    if verified_terms and key in verified_terms:
        entry = verified_terms[key]
        replacement = datetime.fromisoformat(entry["utc"])
        if replacement.tzinfo is None or not entry.get("source"):
            raise ValueError("Verified term requires UTC offset and source")
        if abs((replacement-term.utc).total_seconds()) > 86400:
            raise ValueError("Verified term differs by >1 day; check year/name")
        margin = float(entry.get("margin_minutes", 1))
        if not math.isfinite(margin) or margin < 0:
            raise ValueError("Verified term margin must be finite and nonnegative")
        term = SolarTerm(term.name, replacement.astimezone(UTC), term.month_order,
                         term.longitude, margin, entry["source"])
    return term


def _terms_near(utc: datetime, verified_terms: dict | None = None) -> list[SolarTerm]:
    terms = []
    for year in range(utc.year-1, utc.year+2):
        for month in range(1, 13):
            terms.append(solar_term(year, month, verified_terms))
    return sorted(terms, key=lambda x: x.utc)


def resolve_civil(local: datetime | str, timezone_name: str, *, input_basis: str = "civil", fold: int | None = None) -> dict:
    """Resolve a naive wall-clock reading, rejecting gaps/unspecified folds.

    input_basis='standard' means the supplied reading was ALREADY DST-corrected;
    it is not subtracted a second time. All returned displays describe one UTC
    instant. Standard time is a display, not a reassigned geographic zone.
    """
    if isinstance(local, str):
        local = datetime.fromisoformat(local)
    if local.tzinfo is not None:
        raise ValueError("Supply a naive local datetime plus explicit timezone_name")
    if not timezone_name:
        raise ValueError("Missing timezone; country alone must not silently select a zone")
    if input_basis not in ("civil", "standard"):
        raise ValueError("input_basis must be civil or standard")
    if fold not in (None, 0, 1):
        raise ValueError("fold must be None, 0 or 1")
    zone = ZoneInfo(timezone_name)
    if input_basis == "standard":
        candidate = local.replace(tzinfo=zone)
        std_offset = candidate.utcoffset() - candidate.dst()
        utc = (local-std_offset).replace(tzinfo=UTC)
        civil = utc.astimezone(zone)
        if civil.replace(tzinfo=None)-civil.dst() != local:
            raise ValueError("Standard time lies on an unresolved historical offset change")
    else:
        valid = {}
        for f in (0, 1):
            trial = local.replace(tzinfo=zone, fold=f)
            utc_trial = trial.astimezone(UTC)
            back = utc_trial.astimezone(zone)
            if back.replace(tzinfo=None) == local:
                valid[f] = (utc_trial, back)
        if not valid:
            raise ValueError("Nonexistent civil time during a forward clock transition")
        instants = {x[0] for x in valid.values()}
        if len(instants) > 1 and fold is None:
            raise ValueError("Ambiguous civil time; choose fold=0 or fold=1 explicitly")
        chosen = fold if fold is not None else next(iter(valid))
        if chosen not in valid:
            raise ValueError("Chosen fold is not valid")
        utc, civil = valid[chosen]
    return {"utc": utc, "civil": civil.replace(tzinfo=None),
            "standard": civil.replace(tzinfo=None)-civil.dst(),
            "offset_minutes": civil.utcoffset().total_seconds()/60,
            "dst_minutes": civil.dst().total_seconds()/60, "fold": civil.fold}


def branch_relations(branches: list[str]) -> list[dict]:
    """Syntactic relationships only; no automatic 合化, good/bad, or event."""
    if any(b not in BRANCHES for b in branches):
        raise ValueError("Invalid branch")
    out = []
    groups = {
        "冲": ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥"),
        "六合": ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"),
        "害": ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌"),
        "破": ("子酉", "卯午", "辰丑", "戌未", "寅亥", "巳申"),
        "子卯刑": ("子卯",),
    }
    for i, j in combinations(range(len(branches)), 2):
        a, b = branches[i], branches[j]
        for name, pairs in groups.items():
            if any({a,b} == set(pair) for pair in pairs):
                out.append({"kind": name, "positions": [i,j], "branches": a+b})
        if a == b and a in "辰午酉亥":
            out.append({"kind": "自刑", "positions": [i,j], "branches": a+b})
    present = set(branches)
    for kind, triples in {"三合齐全": ("申子辰", "亥卯未", "寅午戌", "巳酉丑"),
                          "三会齐全": ("寅卯辰", "巳午未", "申酉戌", "亥子丑"),
                          "三刑齐全": ("寅巳申", "丑戌未")}.items():
        for group in triples:
            if set(group) <= present:
                out.append({"kind": kind, "branches": group,
                            "positions": [i for i,b in enumerate(branches) if b in group]})
    return out


def _year_month(utc: datetime, terms: list[SolarTerm]) -> tuple[str, str, SolarTerm, int]:
    lichun = next(t for t in terms if t.name == "立春" and t.utc.year == utc.year)
    year = utc.year if utc >= lichun.utc else utc.year-1
    prev = max((t for t in terms if t.utc <= utc), key=lambda x: x.utc)
    y = year_pillar(year)
    return y, month_pillar(y[0], prev.month_order), prev, year


def chart(local_datetime: datetime | str, timezone_name: str, sex: str, *,
          city: str | None = None, input_basis: str = "civil", time_basis: str,
          day_boundary: str, longitude: float | None = None, fold: int | None = None,
          time_uncertainty_minutes: float = 0, verified_terms: dict | None = None,
          strict_boundary: bool = False) -> dict:
    """Return JSON-serializable calculations; conventions are REQUIRED keywords.

    time_basis: civil/standard/apparent_solar. day_boundary: midnight/zi23.
    No birthplace or time convention is guessed. City is audit metadata;
    callers remain responsible for verifying the explicit IANA zone and longitude.
    """
    if time_basis not in ("civil", "standard", "apparent_solar"):
        raise ValueError("Choose time_basis explicitly")
    if day_boundary not in ("midnight", "zi23"):
        raise ValueError("Choose day_boundary explicitly")
    if sex not in ("male", "female"):
        raise ValueError("sex must be male/female for declared traditional direction rule")
    if not math.isfinite(time_uncertainty_minutes) or not 0 <= time_uncertainty_minutes <= 1440:
        raise ValueError("Time uncertainty must be finite and within 0–1440 minutes; split larger intervals")
    times = resolve_civil(local_datetime, timezone_name, input_basis=input_basis, fold=fold)
    utc = times["utc"]
    if not 1900 <= utc.year <= 2100:
        raise ValueError("Supported chart years: 1900–2100")
    if time_uncertainty_minutes:
        zone = ZoneInfo(timezone_name)
        left = utc-timedelta(minutes=time_uncertainty_minutes)
        right = utc+timedelta(minutes=time_uncertainty_minutes)
        probes = [left, right, utc]
        cursor = left
        while cursor < right:
            probes.append(cursor)
            cursor += timedelta(hours=1)
        offsets = {(p.astimezone(zone).utcoffset(),p.astimezone(zone).dst()) for p in probes}
        if len(offsets) > 1:
            raise ValueError("Uncertainty interval crosses a timezone/DST transition; split the interval and resolve each fold explicitly")
    if time_basis == "apparent_solar":
        if longitude is None or not -180 <= longitude <= 180:
            raise ValueError("Apparent solar time requires verified east-positive longitude")
        clock = utc.replace(tzinfo=None) + timedelta(minutes=4*longitude+equation_of_time_minutes(utc))
    else:
        clock = times[time_basis]
    terms = _terms_near(utc, verified_terms)
    y, m, prev, solar_year = _year_month(utc, terms)
    effective_day = clock.date() + timedelta(days=int(day_boundary == "zi23" and clock.hour >= 23))
    d = day_pillar(effective_day)
    h = hour_pillar(d[0], clock.hour)
    names = ("year", "month", "day", "hour")
    pillars = dict(zip(names, (y,m,d,h)))
    warnings = []
    if not city:
        warnings.append("City not supplied; timezone/longitude are explicit assumptions, not verified birthplace")
    if time_basis != "apparent_solar" and longitude is None:
        warnings.append("Solar-time alternative is not evaluated because longitude is missing")
    boundary_candidates = []
    for t in terms:
        if abs((utc-t.utc).total_seconds()) <= (t.margin_minutes+time_uncertainty_minutes)*60:
            warnings.append(f"Birth near {t.name}: solar year/month cannot be uniquely assigned with current precision")
            for probe in (t.utc-timedelta(seconds=1), t.utc+timedelta(seconds=1)):
                cy, cm, _, _ = _year_month(probe, terms)
                boundary_candidates.append({"year": cy, "month": cm, "term": t.name})
    clock_margin = time_uncertainty_minutes*60 + (EOT_MARGIN_SECONDS if time_basis == "apparent_solar" else 0)
    clock_candidates = []
    if clock_margin:
        left, right = clock-timedelta(seconds=clock_margin), clock+timedelta(seconds=clock_margin)
        probes = [left, right]
        cursor = left.replace(minute=0, second=0, microsecond=0)
        while cursor <= right:
            if cursor >= left and (cursor.hour % 2 == 1 or cursor.hour == 0):
                probes.extend([cursor, cursor-timedelta(microseconds=1)])
            cursor += timedelta(hours=1)
        for p in probes:
            pd = p.date()+timedelta(days=int(day_boundary == "zi23" and p.hour >= 23))
            dd = day_pillar(pd)
            c = {"day": dd, "hour": hour_pillar(dd[0], p.hour)}
            if c not in clock_candidates:
                clock_candidates.append(c)
        if len(clock_candidates) > 1:
            warnings.append("Clock uncertainty crosses an hour/day boundary; multiple day/hour pillars retained")
    forward = (STEMS.index(y[0]) % 2 == 0) == (sex == "male")
    next_term = min((t for t in terms if t.utc > utc), key=lambda x: x.utc)
    direction_term = next_term if forward else prev
    gap_days = abs((direction_term.utc-utc).total_seconds()) / 86400
    start_age_years = gap_days/3
    # Conversion is a declared implementation choice, not universal doctrine.
    start_utc = utc + timedelta(days=start_age_years*365.2425)
    margin_age_years = (direction_term.margin_minutes+time_uncertainty_minutes)/1440/3
    luck = {"direction": "forward" if forward else "backward", "basis": "year-stem polarity × sex",
            "target_jie": direction_term.name, "target_jie_utc": direction_term.utc.isoformat(),
            "gap_days": round(gap_days,8), "start_age_years": round(start_age_years,8),
            "age_margin_years_operational": round(margin_age_years,8),
            "start_utc_approx": start_utc.isoformat(),
            "start_date_conversion": "3 elapsed birth-to-Jie days = 1 age-year; 1 age-year = 365.2425 elapsed days",
            "uncertain": bool(boundary_candidates),
            "cycles": [{"pillar": ganzhi(cycle_index(m)+(1 if forward else -1)*i),
                        "start_age_years": round(start_age_years+(i-1)*10,8)} for i in range(1,10)]}
    if boundary_candidates:
        luck["warning"] = "Direction, starting month and selected Jie can change at boundary; recompute each verified candidate"
    stem_gods = {name: ("日主" if name == "day" else ten_god(d[0],p[0])) for name,p in pillars.items()}
    hidden = {name: [{"stem": s,"ten_god":ten_god(d[0],s)} for s in HIDDEN[p[1]]] for name,p in pillars.items()}
    result = {"model": MODEL_VERSION, "input": {"local_datetime": str(local_datetime), "timezone": timezone_name,
            "city": city, "sex": sex, "input_basis": input_basis, "time_basis": time_basis,
            "day_boundary": day_boundary, "longitude_east": longitude,
            "time_uncertainty_minutes": time_uncertainty_minutes},
            "time": {**{k:v.isoformat() if isinstance(v,datetime) else v for k,v in times.items()},
                     "selected_clock": clock.isoformat(), "effective_day": effective_day.isoformat()},
            "solar_year": solar_year, "pillars": pillars, "stem_ten_gods": stem_gods,
            "solar_context": {"previous_jie": {"name":prev.name,"utc":prev.utc.isoformat(),"source":prev.source,"margin_minutes":prev.margin_minutes},
                              "next_jie": {"name":next_term.name,"utc":next_term.utc.isoformat(),"source":next_term.source,"margin_minutes":next_term.margin_minutes}},
            "hidden_stems": hidden, "branch_relations": branch_relations([p[1] for p in pillars.values()]),
            "year_month_candidates": boundary_candidates, "day_hour_candidates": clock_candidates,
            "luck": luck, "warnings": warnings,
            "precision": {"solar_model": "HKO 2013/2016 minute tables, otherwise pinned Astronomy Engine; no universal timing bound claimed", "ephemeris_commit": EPHEMERIS_COMMIT,
                          "tzdata_version": tzdata_version(), "term_buffer_minutes": SOLAR_MARGIN_MINUTES,
                          "buffer_is_proven_error_bound": False, "equation_of_time_buffer_seconds": EOT_MARGIN_SECONDS,
                          "equation_of_time_model": "Meeus/NOAA-style approximate formula",
                          "verified_term_overrides": bool(verified_terms), "bundled_hko_years": sorted(HKO_JIE_FIXTURES)}}
    result["usable_for_single_chart_interpretation"] = not boundary_candidates and len(clock_candidates) <= 1
    if strict_boundary and not result["usable_for_single_chart_interpretation"]:
        raise CalendarBoundaryError(result)
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("local_datetime")
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--sex", choices=("male","female"), required=True)
    parser.add_argument("--basis", choices=("civil","standard","apparent_solar"), required=True)
    parser.add_argument("--day-boundary", choices=("midnight","zi23"), required=True)
    parser.add_argument("--input-basis", choices=("civil","standard"), default="civil")
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--city")
    parser.add_argument("--uncertainty-minutes", type=float, default=0)
    args = parser.parse_args()
    print(json.dumps(chart(args.local_datetime,args.timezone,args.sex,city=args.city,input_basis=args.input_basis,
                           time_basis=args.basis,day_boundary=args.day_boundary,longitude=args.longitude,
                           time_uncertainty_minutes=args.uncertainty_minutes),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    _main()
