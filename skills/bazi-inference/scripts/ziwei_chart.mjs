#!/usr/bin/env node
/** Local calculation only. Invoke this CLI in a fresh process for each profile. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { buildAnnualPeriods, buildEvidenceContext, renderEvidenceMarkdown } from './ziwei_context.mjs';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const profileBytes = fs.readFileSync(path.join(root, 'assets/ziwei-profile.json'));
const profileTemplate = JSON.parse(profileBytes);
const help = `Local Ziwei chart adapter (optional dependency: npm ci --ignore-scripts)
Usage: node scripts/ziwei_chart.mjs --input normalized.json [--output chart.json]
       [--day-divide current|forward] [--markdown context.md]
       [--palaces 命宫,官禄,财帛,夫妻,子女,疾厄]

Input JSON (dates must be real Gregorian dates within 1901-2099):
{
  "schema_version": "ziwei-normalized-input/v1",
  "solar_date": "2000-08-16", "hour_index": 2, "sex": "female",
  "normalization": {
    "status": "confirmed", "clock_basis": "civil",
    "note": "Upstream verified historical timezone/DST; no solar-time correction."
  },
  "targets": [{"solar_date": "2023-10-26", "hour_index": 0}],
  "years": [2023, 2024]
}
hour_index: 0=00:00-00:59, 1=01:00-02:59, ... 11=21:00-22:59,
12=23:00-23:59. Each clock_time, when supplied, must agree with its index.
normalization.status: confirmed|scenario; clock_basis: civil|standard|apparent_solar.
Unknown fields are rejected. Raw birth location and civil timestamps must first
be resolved by the calendar layer; this adapter does not perform timezone, DST,
longitude or true-solar conversion. Separate uncertain clocks into separate inputs.
The default profile uses normal year/horoscope/age division, current late-Zi day,
default algorithm, fixLeap=true and pinned complete four-transform/brightness tables.
The forward switch makes an explicitly labelled alternate profile; do not replace
the birth date manually as well. Targets are explicit snapshots, not whole-year
coverage. Optional years (max 50 distinct years) scans civil dates and returns
contiguous decadal/yearly/nominal-age segments under this normal-year profile.
Birth-year coverage is clipped at birth. Monthly/daily/hourly layers are NOT
covered by these segments. evidence_context exposes separate natal/decadal/yearly
palace maps, surrounding palaces, four-transform sources and scoped moving stars.
--markdown writes a selected-palace reading sheet; --palaces affects only this
sheet, never the complete JSON. Output contains calculations, not predictions
or medical diagnoses.
No birth data is sent to a network service. Input '-' reads standard input.
`;

function fail(message) { throw new Error(message); }
function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label} must be an object`);
}
function only(value, keys, label) {
  object(value, label);
  for (const key of Object.keys(value)) if (!keys.includes(key)) fail(`${label}: unknown field ${key}`);
}
function date(value, label) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) fail(`${label} must be YYYY-MM-DD`);
  const [y, m, d] = value.split('-').map(Number);
  if (y < 1901 || y > 2099 || m < 1 || m > 12 || d < 1 ||
      d > new Date(Date.UTC(y, m, 0)).getUTCDate()) fail(`${label} is invalid or outside 1901-2099`);
  return value;
}
function clock(value, label) {
  date(value.solar_date, `${label}.solar_date`);
  if (!Number.isInteger(value.hour_index) || value.hour_index < 0 || value.hour_index > 12)
    fail(`${label}.hour_index must be an explicit integer 0..12`);
  if (value.clock_time !== undefined) {
    if (typeof value.clock_time !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value.clock_time))
      fail(`${label}.clock_time must be HH:MM`);
    const h = Number(value.clock_time.slice(0, 2));
    if (Math.floor((h + 1) / 2) !== value.hour_index) fail(`${label}.clock_time disagrees with hour_index`);
  }
}
function validate(input) {
  only(input, ['schema_version', 'solar_date', 'hour_index', 'clock_time', 'sex', 'normalization', 'targets', 'years'], 'input');
  if (input.schema_version !== 'ziwei-normalized-input/v1') fail('Unsupported or missing input schema_version');
  clock(input, 'input');
  if (!['male', 'female'].includes(input.sex)) fail('sex must be male or female');
  only(input.normalization, ['status', 'clock_basis', 'note'], 'normalization');
  if (!['confirmed', 'scenario'].includes(input.normalization.status)) fail('normalization.status must be confirmed or scenario');
  if (!['civil', 'standard', 'apparent_solar'].includes(input.normalization.clock_basis)) fail('Invalid normalization.clock_basis');
  if (typeof input.normalization.note !== 'string' || !input.normalization.note.trim()) fail('normalization.note is required');
  if (input.targets !== undefined && (!Array.isArray(input.targets) || input.targets.length > 200)) fail('targets must be an array with at most 200 snapshots');
  for (const [i, target] of (input.targets ?? []).entries()) {
    only(target, ['solar_date', 'hour_index', 'clock_time'], `targets[${i}]`);
    clock(target, `targets[${i}]`);
    if (target.solar_date < input.solar_date || (target.solar_date === input.solar_date && target.hour_index < input.hour_index))
      fail(`targets[${i}] precedes birth`);
    if (target.solar_date === input.solar_date && target.hour_index === input.hour_index &&
        target.clock_time !== undefined && input.clock_time !== undefined && target.clock_time < input.clock_time)
      fail(`targets[${i}] precedes birth clock_time`);
  }
  if (input.years !== undefined && (!Array.isArray(input.years) || input.years.length > 50))
    fail('years must be an array with at most 50 distinct Gregorian years');
  if (new Set(input.years ?? []).size !== (input.years ?? []).length) fail('years must not contain duplicates');
  for (const year of input.years ?? []) {
    if (!Number.isInteger(year) || year < 1901 || year > 2099) fail('years entries must be integer Gregorian years within 1901-2099');
    if (year < Number(input.solar_date.slice(0, 4))) fail('years must not precede the birth year');
  }
}

function calculate(input, dayDivide) {
  validate(input);
  const pkg = require('iztro/package.json');
  if (pkg.version !== profileTemplate.engine.version) fail(`Expected iztro ${profileTemplate.engine.version}; run npm ci --ignore-scripts`);
  const { astro } = require('iztro');
  const profile = structuredClone(profileTemplate);
  profile.config.dayDivide = dayDivide;
  profile.id = `iztro-${pkg.version}-normal-${dayDivide}-default-v1`;
  astro.config(profile.config);
  const resolved = astro.getConfig();
  // Freeze full tables, not just the empty override dictionaries exposed by defaults.
  if (JSON.stringify(resolved) !== JSON.stringify({
    mutagens: profile.config.mutagens, brightness: profile.config.brightness,
    yearDivide: profile.config.yearDivide, ageDivide: profile.config.ageDivide,
    dayDivide: profile.config.dayDivide, horoscopeDivide: profile.config.horoscopeDivide,
    algorithm: profile.config.algorithm,
  })) fail('Engine did not resolve the requested fixed profile');
  const natal = astro.bySolar(input.solar_date, input.hour_index, input.sex === 'male' ? '男' : '女', profile.fixLeap, profile.language);
  const output = {
    schema_version: 'ziwei-chart/v1',
    engine: { ...profile.engine, package_lock_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'package-lock.json'))).digest('hex') },
    profile: { ...profile, resolved_config: resolved, source_profile_sha256: createHash('sha256').update(profileBytes).digest('hex') },
    normalized_input: input,
    natal: natal.toJSON(),
    horoscopes: (input.targets ?? []).map(target => ({ target, data: natal.horoscope(target.solar_date, target.hour_index).toJSON() })),
    notes: [
      'normalization is caller asserted, not verified by this adapter; scenario status remains scenario.',
      'Each CLI call is a separate process because iztro configuration is global.',
      'natal.chineseDate follows this Ziwei profile and must not overwrite a separately verified BaZi chart.',
      'Targets are point snapshots. annual_periods covers only decadal/yearly/nominal-age layers under the fixed normal-year profile; it excludes monthly/daily/hourly layers.',
      'Calculation consistency does not establish accuracy of predictions about a person.',
    ],
  };
  if (output.natal.palaces.length !== 12) fail('Unexpected engine output: expected twelve palaces');
  output.annual_periods = buildAnnualPeriods(natal, input, profile);
  output.evidence_context = buildEvidenceContext(output);
  return output;
}

try {
  const args = process.argv.slice(2);
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    process.stdout.write(help);
  } else {
    const options = {};
    for (let i = 0; i < args.length; i += 2) {
      if (!['--input', '--output', '--day-divide', '--markdown', '--palaces'].includes(args[i]) || !args[i + 1] || args[i + 1].startsWith('--')) fail('Invalid CLI arguments; use --help');
      if (options[args[i]] !== undefined) fail(`Duplicate option ${args[i]}`);
      options[args[i]] = args[i + 1];
    }
    if (!options['--input']) fail('--input is required; use --help');
    const dayDivide = options['--day-divide'] ?? 'current';
    if (!['current', 'forward'].includes(dayDivide)) fail('--day-divide must be current or forward');
    if (options['--palaces'] && !options['--markdown']) fail('--palaces requires --markdown');
    const destinations = [options['--output'], options['--markdown']].filter(Boolean).map(p => path.resolve(p));
    if (new Set(destinations).size !== destinations.length) fail('JSON output and markdown must use different paths');
    if (options['--input'] !== '-' && destinations.includes(path.resolve(options['--input']))) fail('Output must not overwrite input');
    const input = JSON.parse(fs.readFileSync(options['--input'] === '-' ? 0 : options['--input'], 'utf8'));
    const output = calculate(input, dayDivide);
    const markdown = options['--markdown'] ? renderEvidenceMarkdown(output, options['--palaces']?.split(',').map(p => p.trim())) : undefined;
    const encoded = `${JSON.stringify(output, null, 2)}\n`;
    if (options['--output']) {
      fs.writeFileSync(options['--output'], encoded, { mode: 0o600 });
    } else process.stdout.write(encoded);
    if (options['--markdown']) fs.writeFileSync(options['--markdown'], markdown, { mode: 0o600 });
  }
} catch (error) {
  const message = error?.code === 'MODULE_NOT_FOUND' ? 'Optional iztro dependency is missing; run npm ci --ignore-scripts in the skill directory.' : error.message;
  process.stderr.write(`ziwei_chart: ${message}\n`);
  process.exitCode = 2;
}
