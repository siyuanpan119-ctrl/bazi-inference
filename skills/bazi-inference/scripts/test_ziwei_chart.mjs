/** Synthetic adapter checks, not a validation of divination accuracy. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
    input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, env: { ...process.env, ...env },
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

function pointer(output, ref) {
  assert.match(ref, /^#\//);
  return ref.slice(2).split('/').reduce((value, key) => {
    assert.notEqual(value, undefined, ref);
    return value[key.replaceAll('~1', '/').replaceAll('~0', '~')];
  }, output);
}

test('whole 2024 contains Jan 1 and lunar New Year, with no lichun/month/hour false coverage', () => {
  const targets = ['2024-01-01', '2024-02-04', '2024-02-09', '2024-02-10', '2024-07-01', '2024-12-31']
    .flatMap(solar_date => [0, 12].map(hour_index => ({ solar_date, hour_index })));
  const out = chart({ ...base, years: [2024], targets });
  const year = out.annual_periods[0];
  assert.equal(year.coverage.scanned_days, 366);
  assert.equal(year.coverage.status, 'complete_year');
  assert.deepEqual(year.coverage.layers, ['decadal', 'yearly', 'nominal_age']);
  assert.ok(year.coverage.excludes.includes('monthly'));
  assert.equal(year.segments.length, 2);
  const [before, after] = year.segments;
  assert.equal(before.interval.start_inclusive.solar_date, '2024-01-01');
  assert.equal(before.interval.end_exclusive.solar_date, '2024-02-10');
  assert.deepEqual(before.interval.end_exclusive, after.interval.start_inclusive);
  assert.equal(after.interval.end_exclusive.solar_date, '2025-01-01');
  assert.equal(before.layers.yearly.heavenlyStem + before.layers.yearly.earthlyBranch, '癸卯');
  assert.equal(after.layers.yearly.heavenlyStem + after.layers.yearly.earthlyBranch, '甲辰');
  assert.equal(before.layers.nominal_age, 24);
  assert.equal(after.layers.nominal_age, 25);
  assert.deepEqual(after.starts_because, ['yearly', 'nominal_age']);
  for (const { target, data } of out.horoscopes) {
    const segment = target.solar_date < '2024-02-10' ? before : after;
    assert.deepEqual(segment.layers.yearly, data.yearly);
    assert.deepEqual(segment.layers.decadal, data.decadal);
    assert.equal(segment.layers.nominal_age, data.age.nominalAge);
    assert.equal(segment.layers.monthly, undefined);
    assert.equal(segment.layers.hourly, undefined);
  }
});

test('normal-year boundary also changes childhood to first decadal at nominal age three', () => {
  const out = chart({ ...base, years: [2002], targets: [
    { solar_date: '2002-02-11', hour_index: 12 }, { solar_date: '2002-02-12', hour_index: 0 },
  ] });
  const [before, after] = out.annual_periods[0].segments;
  assert.equal(before.interval.end_exclusive.solar_date, '2002-02-12');
  assert.equal(before.layers.decadal.name, '童限');
  assert.equal(before.layers.nominal_age, 2);
  assert.equal(after.layers.decadal.name, '大限');
  assert.equal(after.layers.nominal_age, 3);
  assert.equal(after.layers.decadal.index, out.natal.palaces.find(p => p.name === '命宫').index);
  assert.deepEqual(after.starts_because, ['decadal', 'yearly', 'nominal_age']);
  assert.deepEqual(out.horoscopes[0].data.decadal, before.layers.decadal);
  assert.deepEqual(out.horoscopes[1].data.decadal, after.layers.decadal);
  const contextAfter = out.evidence_context.frames.find(f => f.id === after.id);
  assert.deepEqual(contextAfter.layers.decadal.nominal_age_range, [3, 12]);
});

test('birth year is partial, clips at declared clock, and adds no inferred birth minute', () => {
  const precise = chart({ ...base, hour_index: 12, clock_time: '23:15', years: [2000] });
  const year = precise.annual_periods[0];
  assert.equal(year.coverage.status, 'partial_birth_year');
  assert.equal(year.coverage.birth_clipped, true);
  assert.deepEqual(year.covered_interval.start_inclusive, { solar_date: base.solar_date, hour_index: 12, clock_time: '23:15' });
  assert.deepEqual(year.segments[0].starts_because, ['birth_date_clipped']);
  const imprecise = chart({ ...base, years: [2000] });
  assert.equal(imprecise.annual_periods[0].covered_interval.start_inclusive.clock_time, undefined);
  assert.equal(imprecise.normalized_input.clock_time, undefined);
});

test('years are additive: all explicit snapshots and natal data retain backward-compatible values', () => {
  const input = { ...base, targets: [{ solar_date: '2024-03-15', hour_index: 0 }] };
  const snapshotOnly = chart(input);
  const complete = chart({ ...input, years: [2024] });
  assert.deepEqual(complete.natal, snapshotOnly.natal);
  assert.deepEqual(complete.horoscopes, snapshotOnly.horoscopes);
  assert.deepEqual(snapshotOnly.annual_periods, []);
  assert.equal(complete.schema_version, 'ziwei-chart/v1');
  const frame = complete.evidence_context.frames.find(f => f.id === 'snapshot-1');
  const yearFrame = complete.evidence_context.frames.find(f => f.id === 'year-2024-segment-2');
  for (const scope of ['decadal', 'yearly']) {
    assert.equal(frame.layers[scope].id, yearFrame.layers[scope].id);
    assert.deepEqual(frame.layers[scope].four_transformations.map(t => t.id), yearFrame.layers[scope].four_transformations.map(t => t.id));
  }
  // Paths locate distinct raw representations while stable IDs identify one signal.
  assert.notEqual(frame.layers.yearly.four_transformations[0].source_ref, yearFrame.layers.yearly.four_transformations[0].source_ref);
});

test('evidence sources resolve; transformations retain scope, target maps and fixed geometry', () => {
  const out = chart({ ...base, years: [2024], targets: [{ solar_date: '2024-06-01', hour_index: 3 }] });
  const ctx = out.evidence_context;
  const byId = new Map(ctx.palace_catalog.map(p => [p.id, p]));
  function walk(value) {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      if (key === 'source_ref' || key.endsWith('_source_ref')) assert.notEqual(pointer(out, child), undefined, child);
      else walk(child);
    }
  }
  walk(ctx);
  const layers = [ctx.natal_layer, ...ctx.frames.flatMap(f => Object.values(f.layers))];
  for (const layer of layers) {
    assert.equal(layer.palace_map.length, 12);
    assert.equal(new Set(layer.palace_map.map(p => p.name)).size, 12);
    for (const entry of layer.palace_map) {
      assert.equal(byId.get(entry.natal_palace_ref).index, entry.index);
      assert.equal(byId.get(entry.surrounding_refs.opposite).index, (entry.index + 6) % 12);
      assert.equal(byId.get(entry.surrounding_refs.trine_plus4).index, (entry.index + 4) % 12);
      assert.equal(byId.get(entry.surrounding_refs.trine_plus8).index, (entry.index + 8) % 12);
    }
    assert.deepEqual(layer.four_transformations.map(t => t.kind), ['禄', '权', '科', '忌']);
    for (const t of layer.four_transformations) {
      assert.equal(t.source_scope, layer.scope);
      assert.equal(t.source_stem, pointer(out, t.stem_source_ref));
      assert.equal(t.placements.length, 1);
      assert.equal(pointer(out, t.placements[0].physical_star_source_ref).name, t.star);
      assert.equal(pointer(out, t.source_ref), layer.scope === 'natal' ? t.kind : t.star);
      const palace = byId.get(t.placements[0].natal_palace_ref);
      assert.equal(t.placements[0].scope_palace, layer.palace_map[palace.index].name);
    }
    (layer.moving_stars ?? []).forEach(star => {
      assert.equal(star.source_scope, layer.scope);
      assert.equal(pointer(out, star.source_ref).name, star.name);
    });
  }
  const yearly = ctx.frames.find(f => f.id === 'year-2024-segment-2').layers.yearly;
  assert.deepEqual(yearly.four_transformations.map(t => t.star), ['廉贞', '破军', '武曲', '太阳']);
  assert.equal(yearly.four_transformations[2].placements[0].natal_palace, '财帛');
  // The same physical 武曲 carries natal 权 and annual 科, with distinct source IDs.
  const natalWu = ctx.natal_layer.four_transformations.find(t => t.star === '武曲');
  assert.equal(natalWu.kind, '权');
  assert.equal(natalWu.placements[0].physical_star_ref, yearly.four_transformations[2].placements[0].physical_star_ref);
  assert.notEqual(natalWu.id, yearly.four_transformations[2].id);
});

test('whole-year boundaries preserve explicit forward profile and are machine-timezone invariant', () => {
  const input = { ...base, hour_index: 12, years: [2024] };
  const utc = chart(input, ['--day-divide', 'forward'], { TZ: 'UTC' });
  const losAngeles = chart(input, ['--day-divide', 'forward'], { TZ: 'America/Los_Angeles' });
  assert.deepEqual(utc, losAngeles);
  assert.equal(utc.profile.config.dayDivide, 'forward');
  assert.equal(utc.annual_periods[0].segments[1].interval.start_inclusive.solar_date, '2024-02-10');
});

test('year limits, duplicate years, prebirth minutes and CLI destinations are validated', () => {
  const invalid = [
    { ...base, years: '2024' }, { ...base, years: [2024, 2024] },
    { ...base, years: [1999] }, { ...base, years: [2100] }, { ...base, years: [2024.5] },
    { ...base, years: Array.from({ length: 51 }, (_, i) => 2000 + i) },
    { ...base, clock_time: '03:50', targets: [{ solar_date: base.solar_date, hour_index: 2, clock_time: '03:10' }] },
  ];
  invalid.forEach(input => assert.equal(run(input).status, 2, JSON.stringify(input)));
  assert.equal(run(base, ['--palaces', '夫妻']).status, 2);
  assert.equal(run(base, ['--output', '/tmp/zw-same', '--markdown', '/tmp/zw-same']).status, 2);
  const dir = mkdtempSync(path.join(tmpdir(), 'ziwei-evidence-'));
  try {
    const markdown = path.join(dir, 'context.md');
    const json = path.join(dir, 'chart.json');
    const result = run({ ...base, years: [2024] }, ['--output', json, '--markdown', markdown, '--palaces', '夫妻,官禄']);
    assert.equal(result.status, 0, result.stderr);
    const text = readFileSync(markdown, 'utf8');
    assert.match(text, /normalization: confirmed/);
    assert.match(text, /2024-02-10/);
    assert.match(text, /\[natal\]/);
    assert.match(text, /\[decadal\]/);
    assert.match(text, /\[yearly\]/);
    assert.match(text, /不是独立投票/);
    assert.match(text, /流月、流日、流时需另给明确 targets/);
    assert.equal(JSON.parse(readFileSync(json, 'utf8')).evidence_context.natal_layer.palace_map.length, 12);
    assert.equal(run(base, ['--markdown', markdown, '--palaces', '错宫']).status, 2);
    const inputFile = path.join(dir, 'input.json');
    writeFileSync(inputFile, JSON.stringify(base));
    const same = spawnSync(process.execPath, [script, '--input', inputFile, '--markdown', inputFile], { encoding: 'utf8' });
    assert.equal(same.status, 2);
    assert.deepEqual(JSON.parse(readFileSync(inputFile, 'utf8')), base);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
