/** Derived, traceable calculation context. No life-event prediction rules. */
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const TRANSFORMS = ['禄', '权', '科', '忌'];
const GROUPS = ['majorStars', 'minorStars', 'adjectiveStars'];
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex').slice(0, 16);
const nextDate = value => new Date(Date.parse(`${value}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
const midnight = solar_date => ({ solar_date, hour_index: 0, clock_time: '00:00' });

function annualState(data) {
  return { decadal: data.decadal, yearly: data.yearly, nominal_age: data.age.nominalAge };
}

/**
 * Exhaustive civil-date calendar scan for the pinned normal/normal profile. Its year and
 * nominal-age layers change on lunar New Year at the date boundary, not lichun,
 * birthday, monthly/day/hour boundaries. Birth-year coverage is clipped at birth.
 * Segments intentionally omit monthly, daily and hourly data: those are NOT
 * constant over the interval. Explicit targets remain available for those layers.
 */
export function buildAnnualPeriods(natal, input, profile) {
  if (!(input.years?.length)) return [];
  if (profile.config.horoscopeDivide !== 'normal' || profile.config.ageDivide !== 'normal') {
    throw new Error('Whole-year coverage currently requires normal horoscopeDivide and ageDivide');
  }
  // This is the exact calendar dependency used in iztro's horoscope calculation.
  // Its lunar year determines BOTH normal yearly stem/branch and normal nominal
  // age, which in turn selects the decadal/childhood layer. Do not generalize this
  // optimization to a different year/age profile without new boundary logic.
  const { solar2lunar } = require('lunar-lite');
  return [...input.years].sort((a, b) => a - b).map(year => {
    const requestedStart = `${year}-01-01`;
    const end = `${year + 1}-01-01`;
    const firstDate = requestedStart < input.solar_date ? input.solar_date : requestedStart;
    const birthClipped = firstDate === input.solar_date;
    const start = birthClipped
      ? { solar_date: firstDate, hour_index: input.hour_index, ...(input.clock_time ? { clock_time: input.clock_time } : {}) }
      : midnight(firstDate);
    let previousFingerprint;
    let previousLunarYear;
    let scannedDays = 0;
    const segments = [];
    for (let day = firstDate; day < end; day = nextDate(day)) {
      const lunarYear = solar2lunar(day).lunarYear;
      scannedDays++;
      if (lunarYear === previousLunarYear) continue;
      previousLunarYear = lunarYear;
      const target = day === firstDate ? start : midnight(day);
      const raw = natal.horoscope(target.solar_date, target.hour_index).toJSON();
      if (raw.decadal.index < 0 || raw.decadal.index > 11) {
        throw new Error(`No supported decadal/childhood layer at ${day}; whole-year coverage cannot be certified`);
      }
      const state = annualState(raw);
      const fingerprint = hash(state);
      if (fingerprint !== previousFingerprint) {
        const changes = segments.length ? ['decadal', 'yearly', 'nominal_age'].filter(key =>
          JSON.stringify(segments.at(-1).layers[key]) !== JSON.stringify(state[key])) : [];
        if (segments.length) segments.at(-1).interval.end_exclusive = midnight(day);
        segments.push({
          id: `year-${year}-segment-${segments.length + 1}`,
          interval: { start_inclusive: target, end_exclusive: midnight(end) },
          starts_because: segments.length ? changes : [birthClipped ? 'birth_date_clipped' : 'gregorian_year_start'],
          representative_target: target,
          layer_fingerprint: fingerprint,
          layers: state,
        });
        previousFingerprint = fingerprint;
      }
    }
    // Verify each segment's final date against the full engine, including all
    // annual moving stars and four transforms; monthly/daily/hourly are excluded.
    for (const segment of segments) {
      const lastDay = new Date(Date.parse(`${segment.interval.end_exclusive.solar_date}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);
      const last = natal.horoscope(lastDay, 12).toJSON();
      if (hash(annualState(last)) !== segment.layer_fingerprint) {
        throw new Error(`Annual boundary verification failed at ${lastDay}; cannot certify interval`);
      }
    }
    return {
      year,
      requested_interval: { start_inclusive: midnight(requestedStart), end_exclusive: midnight(end) },
      covered_interval: { start_inclusive: start, end_exclusive: midnight(end) },
      coverage: {
        granularity: 'civil_date', layers: ['decadal', 'yearly', 'nominal_age'], scanned_days: scannedDays,
        status: birthClipped ? 'partial_birth_year' : 'complete_year',
        method: 'Every covered civil date scanned with iztro lunar-lite calendar; full engine queried at each normal-year change and segment final date. Only normal yearly/age profile is supported.',
        profile_id: profile.id, birth_clipped: birthClipped,
        excludes: ['monthly', 'daily', 'hourly', 'solar_terms', 'timezone_or_DST_resolution', 'birth_clock_uncertainty'],
      },
      segments,
    };
  });
}

function catalog(natal, chartId) {
  return natal.palaces.map((palace, i) => ({
    id: `${chartId}:natal:palace:${i}`, source_ref: `#/natal/palaces/${i}`,
    index: i, name: palace.name, stem_branch: palace.heavenlyStem + palace.earthlyBranch,
    is_body: palace.isBodyPalace, is_original: palace.isOriginalPalace,
    stars: GROUPS.flatMap(group => (palace[group] ?? []).map((star, j) => ({
      id: `${chartId}:natal:star:${i}:${group}:${j}`,
      source_ref: `#/natal/palaces/${i}/${group}/${j}`,
      name: star.name, group, brightness: star.brightness ?? '',
      // Natal transformation belongs to the natal layer below, never silently
      // attached to the decadal or yearly copy of a palace.
    }))),
  }));
}

function palaceMap(names, palaces) {
  return names.map((name, index) => ({
    name, index, natal_palace_ref: palaces[index].id,
    surrounding_refs: {
      target: palaces[index].id, opposite: palaces[(index + 6) % 12].id,
      trine_plus4: palaces[(index + 4) % 12].id, trine_plus8: palaces[(index + 8) % 12].id,
    },
  }));
}

function transformations(mutagens, layer, palaces, paths) {
  return TRANSFORMS.map((kind, index) => {
    const star = mutagens[index];
    const places = palaces.flatMap(palace => palace.stars.filter(s => s.name === star).map(s => ({
      natal_palace_ref: palace.id, natal_palace: palace.name,
      scope_palace: layer.palace_map[palace.index].name,
      physical_star_ref: s.id, physical_star_source_ref: s.source_ref,
    })));
    if (places.length !== 1) throw new Error(`Expected one natal placement for ${layer.scope} ${star}化${kind}`);
    return {
      id: `${layer.id}:transform:${kind}`, kind, star,
      source_scope: layer.scope, source_stem: layer.heavenly_stem,
      source_ref: paths[index], stem_source_ref: layer.stem_source_ref,
      placements: places,
    };
  });
}

function natalLayer(output, palaces, chartId) {
  const allStars = output.natal.palaces.flatMap((p, i) => GROUPS.flatMap(g =>
    (p[g] ?? []).map((s, j) => ({ ...s, source_ref: `#/natal/palaces/${i}/${g}/${j}/mutagen` }))));
  const ordered = TRANSFORMS.map(kind => {
    const matches = allStars.filter(s => s.mutagen === kind);
    if (matches.length !== 1) throw new Error(`Expected one natal 化${kind} in pinned profile`);
    return matches[0];
  });
  const layer = {
    id: `${chartId}:natal`, scope: 'natal', name: '本命', source_ref: '#/natal',
    heavenly_stem: output.natal.rawDates.chineseDate.yearly[0],
    stem_source_ref: '#/natal/rawDates/chineseDate/yearly/0',
    palace_map: palaceMap(palaces.map(p => p.name), palaces),
  };
  layer.four_transformations = transformations(ordered.map(s => s.name), layer, palaces, ordered.map(s => s.source_ref));
  return layer;
}

function movingLayer(scope, data, nominalAge, source, output, palaces, chartId) {
  const range = scope === 'decadal' && data.name !== '童限'
    ? output.natal.palaces[data.index]?.decadal?.range : undefined;
  const identity = { index: data.index, stem: data.heavenlyStem, branch: data.earthlyBranch,
    name: data.name, period: scope === 'yearly' || data.name === '童限' ? nominalAge : range };
  const layer = {
    id: `${chartId}:${scope}:${hash(identity)}`, scope, name: data.name, source_ref: source,
    heavenly_stem: data.heavenlyStem, earthly_branch: data.earthlyBranch,
    stem_source_ref: `${source}/heavenlyStem`, life_palace_index: data.index,
    ...(range ? { nominal_age_range: range } : {}),
    palace_map: palaceMap(data.palaceNames, palaces),
  };
  layer.four_transformations = transformations(data.mutagen, layer, palaces, TRANSFORMS.map((_, i) => `${source}/mutagen/${i}`));
  layer.moving_stars = (data.stars ?? []).flatMap((stars, i) => stars.map((star, j) => ({
    id: `${layer.id}:star:${i}:${j}`, source_scope: scope, name: star.name, type: star.type,
    source_ref: `${source}/stars/${i}/${j}`, natal_palace_ref: palaces[i].id,
    scope_palace: data.palaceNames[i],
  })));
  if (data.yearlyDecStar) {
    layer.annual_auxiliary_cycles = Object.entries(data.yearlyDecStar).flatMap(([cycle, stars]) =>
      stars.map((name, i) => ({ id: `${layer.id}:${cycle}:${i}`, source_scope: scope, cycle, name,
        source_ref: `${source}/yearlyDecStar/${cycle}/${i}`, natal_palace_ref: palaces[i].id,
        scope_palace: data.palaceNames[i] })));
  }
  return layer;
}

/** Stable evidence ids deduplicate a signal across snapshots and palace views.
 * Shared physical_star_ref is also explicit: repeated views do not create
 * independent evidence and different layers are correlated, not independent votes.
 */
export function buildEvidenceContext(output) {
  const chartId = `zw-${hash({
    solar_date: output.normalized_input.solar_date, hour_index: output.normalized_input.hour_index,
    sex: output.normalized_input.sex, profile: output.profile,
  })}`;
  const palaces = catalog(output.natal, chartId);
  const frames = [];
  const addFrame = (id, data, nominalAge, source, interval, target) => {
    frames.push({
      id, source_ref: source, ...(interval ? { interval } : {}), ...(target ? { target } : {}), nominal_age: nominalAge,
      layers: {
        decadal: movingLayer('decadal', data.decadal, nominalAge, `${source}/decadal`, output, palaces, chartId),
        yearly: movingLayer('yearly', data.yearly, nominalAge, `${source}/yearly`, output, palaces, chartId),
      },
    });
  };
  output.horoscopes.forEach((h, i) => addFrame(`snapshot-${i + 1}`, h.data, h.data.age.nominalAge,
    `#/horoscopes/${i}/data`, undefined, h.target));
  (output.annual_periods ?? []).forEach((year, y) => year.segments.forEach((segment, s) =>
    addFrame(segment.id, segment.layers, segment.layers.nominal_age,
      `#/annual_periods/${y}/segments/${s}/layers`, segment.interval, segment.representative_target)));
  return {
    schema_version: 'ziwei-evidence-context/v1', chart_id: chartId,
    normalization_status: output.normalized_input.normalization.status,
    geometry: 'Each target plus opposite(+6), trine(+4), trine(+8); names belong to the selected scope. Indices use natal fixed branch positions.',
    read_order: ['natal selected palace and surrounding refs', 'decadal same named target and surrounding refs',
      'yearly same named target and surrounding refs', 'each layer four_transformations and moving_stars', 'competing event explanations'],
    deduplication: 'An id denotes the same calculated signal across views/snapshots. Count it once per event window. Shared physical_star_ref identifies the same natal star; multiple scopes are not independent votes.',
    excluded_inferences: 'No event diagnosis, no astrology-derived probability, no automatic prediction from a single palace/star/transformation.',
    excluded_layers: ['monthly', 'daily', 'hourly', 'palace-stem flying transformations', 'self-transformations'],
    palace_catalog: palaces,
    natal_layer: natalLayer(output, palaces, chartId), frames,
  };
}

export const DEFAULT_PALACES = ['命宫', '官禄', '财帛', '夫妻', '子女', '疾厄'];

export function renderEvidenceMarkdown(output, selected = DEFAULT_PALACES) {
  const context = output.evidence_context;
  const byId = new Map(context.palace_catalog.map(p => [p.id, p]));
  const valid = context.palace_catalog.map(p => p.name);
  if (!selected.length || selected.some(name => !valid.includes(name)) || new Set(selected).size !== selected.length) {
    throw new Error(`--palaces must be distinct names from: ${valid.join(',')}`);
  }
  const lines = [
    '# 紫微分层计算底稿', '',
    `Profile: ${output.profile.id}; normalization: ${context.normalization_status}.`,
    `选读宫位：${selected.join('、')}。完整12宫、四化、流曜及源字段保留于 JSON。`,
    '这是计算底稿，不是事件预测。年度区段只覆盖流年、大限与虚岁；流月、流日、流时需另给明确 targets。',
    '同一证据 ID 只计一次；同星在多层出现不是独立投票。空宫也须读取三方四正，不自动判为缺失某个人或事件。', '',
  ];
  const showLayer = layer => {
    lines.push(`### ${layer.name} [${layer.scope}] ${layer.heavenly_stem}${layer.earthly_branch ?? ''}`, '', `来源：\`${layer.source_ref}\`。`, '');
    lines.push('| 目标宫 | 本命落宫 | 三方四正（固定地支） |', '|---|---|---|');
    const referenced = new Set();
    for (const name of selected) {
      const entry = layer.palace_map.find(p => p.name === name);
      const places = Object.values(entry.surrounding_refs).map(id => byId.get(id));
      places.forEach(p => referenced.add(p.id));
      const natal = byId.get(entry.natal_palace_ref);
      lines.push(`| ${name} | ${natal.name}·${natal.stem_branch} | ${places.map(p => `${p.name}·${p.stem_branch}`).join(' / ')} |`);
    }
    lines.push('', '四化（来源层必须保留）：', '');
    layer.four_transformations.forEach(t => lines.push(`- ${layer.name}${t.source_stem}干：${t.star}化${t.kind} → 本命${t.placements[0].natal_palace} / 本层${t.placements[0].scope_palace}；ID \`${t.id}\`；来源 \`${t.source_ref}\`。`));
    if (layer.moving_stars) {
      lines.push('', '相关宫及三方四正流曜：', '');
      for (const ref of referenced) {
        const stars = layer.moving_stars.filter(s => s.natal_palace_ref === ref);
        if (stars.length) lines.push(`- 本命${byId.get(ref).name}：${stars.map(s => `${s.name}[${s.source_scope}]`).join('、')}；来源 \`${layer.source_ref}/stars/${byId.get(ref).index}\`。`);
      }
    }
    lines.push('');
  };
  lines.push('## 本命星曜目录', '', '| 本命宫 | 地支 | 主星 / 辅星 | 原始字段 |', '|---|---|---|---|');
  context.palace_catalog.forEach(p => lines.push(`| ${p.name}${p.is_body ? '（身宫）' : ''} | ${p.stem_branch} | ${p.stars.filter(s => s.group !== 'adjectiveStars').map(s => s.name + s.brightness).join('、') || '无主辅星'} | \`${p.source_ref}\` |`));
  lines.push('');
  showLayer(context.natal_layer);
  for (const frame of context.frames) {
    const startClock = frame.interval?.start_inclusive.clock_time ??
      (frame.interval ? `时辰索引${frame.interval.start_inclusive.hour_index}（分钟未给）` : '');
    const label = frame.interval
      ? `${frame.interval.start_inclusive.solar_date} ${startClock} ≤ 时间 < ${frame.interval.end_exclusive.solar_date} 00:00`
      : `${frame.target.solar_date} 时辰索引 ${frame.target.hour_index}（单点快照）`;
    lines.push(`## ${frame.id}: ${label}`, '', `虚岁：${frame.nominal_age}。`, '');
    showLayer(frame.layers.decadal);
    showLayer(frame.layers.yearly);
  }
  return `${lines.join('\n')}\n`;
}
