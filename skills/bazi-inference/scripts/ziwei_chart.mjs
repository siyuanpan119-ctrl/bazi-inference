#!/usr/bin/env node
/** Local calculation only. Invoke this CLI in a fresh process for each profile. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const profileBytes = fs.readFileSync(path.join(root, 'assets/ziwei-profile.json'));
const profileTemplate = JSON.parse(profileBytes);
const help = `Local Ziwei chart adapter (optional dependency: npm ci --ignore-scripts)
Usage: node scripts/ziwei_chart.mjs --input normalized.json [--output chart.json]
       [--day-divide current|forward]

Input JSON (dates must be real Gregorian dates within 1901-2099):
{
  "schema_version": "ziwei-normalized-input/v1",
  "solar_date": "2000-08-16", "hour_index": 2, "sex": "female",
  "normalization": {
    "status": "confirmed", "clock_basis": "civil",
    "note": "Upstream verified historical timezone/DST; no solar-time correction."
  },
  "targets": [{"solar_date": "2023-10-26", "hour_index": 0}]
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
coverage. Output contains calculations, not predictions or medical diagnoses.
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
  only(input, ['schema_version', 'solar_date', 'hour_index', 'clock_time', 'sex', 'normalization', 'targets'], 'input');
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
      'Snapshot boundaries follow the declared profile. Annual/monthly reports require all relevant boundary snapshots.',
      'Calculation consistency does not establish accuracy of predictions about a person.',
    ],
  };
  if (output.natal.palaces.length !== 12) fail('Unexpected engine output: expected twelve palaces');
  return output;
}

try {
  const args = process.argv.slice(2);
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    process.stdout.write(help);
  } else {
    const options = {};
    for (let i = 0; i < args.length; i += 2) {
      if (!['--input', '--output', '--day-divide'].includes(args[i]) || !args[i + 1] || args[i + 1].startsWith('--')) fail('Invalid CLI arguments; use --help');
      if (options[args[i]] !== undefined) fail(`Duplicate option ${args[i]}`);
      options[args[i]] = args[i + 1];
    }
    if (!options['--input']) fail('--input is required; use --help');
    const dayDivide = options['--day-divide'] ?? 'current';
    if (!['current', 'forward'].includes(dayDivide)) fail('--day-divide must be current or forward');
    const input = JSON.parse(fs.readFileSync(options['--input'] === '-' ? 0 : options['--input'], 'utf8'));
    const encoded = `${JSON.stringify(calculate(input, dayDivide), null, 2)}\n`;
    if (options['--output']) {
      if (options['--input'] !== '-' && path.resolve(options['--output']) === path.resolve(options['--input'])) fail('Output must not overwrite input');
      fs.writeFileSync(options['--output'], encoded, { mode: 0o600 });
    } else process.stdout.write(encoded);
  }
} catch (error) {
  const message = error?.code === 'MODULE_NOT_FOUND' ? 'Optional iztro dependency is missing; run npm ci --ignore-scripts in the skill directory.' : error.message;
  process.stderr.write(`ziwei_chart: ${message}\n`);
  process.exitCode = 2;
}
