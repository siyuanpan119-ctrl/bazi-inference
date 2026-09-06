/** Synthetic adapter checks, not a validation of divination accuracy. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const script = fileURLToPath(new URL('./ziwei_chart.mjs', import.meta.url));
const base = {
  schema_version: 'ziwei-normalized-input/v1', solar_date: '2000-08-16',
  hour_index: 2, sex: 'female',
  normalization: { status: 'confirmed', clock_basis: 'civil', note: 'Synthetic input from the public upstream quick-start example.' },
};
function run(input = base, extras = [], env = {}) {
  return spawnSync(process.execPath, [script, '--input', '-', ...extras], {
    input: JSON.stringify(input), encoding: 'utf8', env: { ...process.env, ...env },
  });
}
function chart(input = base, extras = [], env = {}) {
  const result = run(input, extras, env);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test('public upstream example: lunar date, four pillars, soul/body palaces and stars', () => {
  // Independently specified values published at https://iztro.com/quick-start
  // They are a compatibility fixture, not independent empirical life-outcome data.
  const out = chart();
  assert.equal(out.schema_version, 'ziwei-chart/v1');
  assert.equal(out.engine.version, '2.6.1');
  assert.equal(out.natal.lunarDate, '二〇〇〇年七月十七');
  assert.equal(out.natal.chineseDate, '庚辰 甲申 丙午 庚寅');
  assert.equal(out.natal.earthlyBranchOfSoulPalace, '午');
  assert.equal(out.natal.earthlyBranchOfBodyPalace, '戌');
  assert.equal(out.natal.fiveElementsClass, '木三局');
  assert.equal(out.natal.palaces.length, 12);
  assert.deepEqual(out.natal.palaces.find(p => p.name === '命宫').majorStars.map(s => s.name), ['紫微']);
  assert.deepEqual(out.horoscopes, []);
  assert.equal(Object.keys(out.profile.resolved_config.mutagens).length, 10);
  assert.ok(Object.values(out.profile.resolved_config.brightness).every(xs => xs.length === 12));
});

test('late Zi current and forward are explicit different complete charts', () => {
  const input = { ...base, hour_index: 12, clock_time: '23:15' };
  const current = chart(input);
  const forward = chart(input, ['--day-divide', 'forward']);
  assert.deepEqual(current.natal.rawDates.chineseDate.daily, ['丙', '午']);
  assert.deepEqual(forward.natal.rawDates.chineseDate.daily, ['丁', '未']);
  assert.notDeepEqual(current.natal.palaces, forward.natal.palaces);
  assert.notEqual(current.profile.id, forward.profile.id);
  assert.equal(forward.normalized_input.solar_date, base.solar_date);
  // Re-running current in a fresh process cannot inherit forward's global config.
  assert.deepEqual(chart(input).natal, current.natal);
});

test('hour index zero is retained for natal and target; target never uses the current date', () => {
  const input = { ...base, hour_index: 0, targets: [{ solar_date: '2023-10-26', hour_index: 0 }] };
  const out = chart(input);
  assert.equal(out.normalized_input.hour_index, 0);
  assert.equal(out.natal.timeRange, '00:00~01:00');
  assert.equal(out.horoscopes[0].data.solarDate, '2023-10-26');
  assert.equal(out.horoscopes[0].data.hourly.earthlyBranch, '子');
  assert.equal(out.horoscopes[0].data.yearly.heavenlyStem, '癸');
  assert.equal(out.horoscopes[0].data.yearly.earthlyBranch, '卯');
  assert.equal(out.horoscopes[0].data.decadal.palaceNames.length, 12);
});

test('normalized date-only inputs give identical output in different machine timezones', () => {
  const input = { ...base, targets: [{ solar_date: '2024-02-10', hour_index: 0 }] };
  assert.deepEqual(chart(input, [], { TZ: 'UTC' }), chart(input, [], { TZ: 'America/Los_Angeles' }));
});

test('reject impossible dates, invalid clocks, omitted normalization and unknown raw fields', () => {
  const invalid = [
    { ...base, solar_date: '2001-02-29' }, { ...base, solar_date: '2024-04-31' },
    { ...base, solar_date: '1800-01-01' }, { ...base, hour_index: undefined },
    { ...base, hour_index: 13 }, { ...base, hour_index: '0' },
    { ...base, clock_time: '23:10' }, { ...base, sex: 'unknown' },
    { ...base, normalization: undefined }, { ...base, birthplace: 'an unresolved country' },
    { ...base, targets: [{ solar_date: '2023-10-26' }] },
    { ...base, targets: [{ solar_date: '1999-10-26', hour_index: 0 }] },
  ];
  for (const input of invalid) {
    const result = run(input);
    assert.equal(result.status, 2, JSON.stringify(input));
    assert.equal(result.stdout, '');
    assert.match(result.stderr, /ziwei_chart:/);
  }
});

test('unresolved place/time remains a labelled scenario, without changing clock basis', () => {
  const input = { ...base, normalization: { status: 'scenario', clock_basis: 'apparent_solar', note: 'One explicitly proposed city and clock scenario; not confirmed.' } };
  assert.deepEqual(chart(input).normalized_input.normalization, input.normalization);
});

test('CLI output file contains the same calculated schema and help needs no private input', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'ziwei-adapter-'));
  try {
    const filename = path.join(dir, 'chart.json');
    const result = run(base, ['--output', filename]);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, '');
    assert.equal(JSON.parse(readFileSync(filename, 'utf8')).schema_version, 'ziwei-chart/v1');
    const help = spawnSync(process.execPath, [script, '--help'], { encoding: 'utf8' });
    assert.equal(help.status, 0);
    assert.match(help.stdout, /hour_index/);
    assert.equal(run(base, ['--day-divide', 'guess']).status, 2);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
