// Service Ops dashboard: hash routing, one filter model shared by every view, SVG charts.
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = new Intl.NumberFormat('en-US');
const fmt = {
  int: (v) => (v == null ? '–' : nf.format(Math.round(v))),
  pct: (v, d = 1) => (v == null ? '–' : `${Number(v).toFixed(d)}%`),
  hours: (v) => (v == null ? '–' : v >= 48 ? `${(v / 24).toFixed(1)} d` : `${Number(v).toFixed(1)} h`),
  month: (m) => new Date(`${m}-01T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: 'numeric' }),
  monthShort: (m) => new Date(`${m}-01T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
  day: (d) => new Date(`${d}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
};
const ICON = {
  good: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
  warning: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 3 20h18z"/><path d="M12 10v4"/></svg>',
  critical: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.01"/></svg>',
  chevron: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3"/></svg>',
};

const VIEWS = {
  overview: { title: 'Overview', subtitle: 'Volume, backlog, resolution time and SLA compliance' },
  breaches: { title: 'Breach analysis', subtitle: 'Where SLA breaches concentrate, why, and what to change' },
  queues: { title: 'Queues & agents', subtitle: 'Workload and compliance by resolver group and agent' },
  quality: { title: 'Data quality', subtitle: 'Checks applied to the raw export before anything is reported' },
  tickets: { title: 'Tickets', subtitle: 'Every quality-gated ticket with its SLA outcome' },
};
const DIMENSIONS = [
  ['category', 'Category', 'categories'], ['priority', 'Priority', 'priorities'],
  ['group', 'Group', 'groups'], ['site', 'Site', 'sites'], ['channel', 'Channel', 'channels'],
];
const PRESETS = [
  ['all', 'All time', null, null], ['12m', 'Last 12 months', '2025-07-01', '2026-06-30'],
  ['2026', '2026 H1', '2026-01-01', '2026-06-30'], ['2025', '2025', '2025-01-01', '2025-12-31'],
  ['2024', '2024', '2024-01-01', '2024-12-31'],
];

const state = {
  view: 'overview',
  filters: { start: null, end: null, category: [], priority: [], group: [], site: [], channel: [] },
  tickets: { sort: 'opened_at', desc: true, offset: 0, state: '', search: '' },
  meta: null,
  seq: 0,
};

// ---------- URL state ----------
function readHash() {
  const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
  state.view = VIEWS[path] ? path : 'overview';
  const p = new URLSearchParams(query);
  state.filters.start = p.get('start');
  state.filters.end = p.get('end');
  for (const [key] of DIMENSIONS) state.filters[key] = p.getAll(key);
}
function filterParams() {
  const p = new URLSearchParams();
  const f = state.filters;
  if (f.start) p.set('start', f.start);
  if (f.end) p.set('end', f.end);
  for (const [key] of DIMENSIONS) for (const v of f[key]) p.append(key, v);
  return p;
}
function writeHash() {
  const q = filterParams().toString();
  const next = `#/${state.view}${q ? `?${q}` : ''}`;
  if (location.hash !== next) history.replaceState(null, '', next);
}
async function api(path, extra = {}) {
  const p = filterParams();
  for (const [k, v] of Object.entries(extra)) if (v !== '' && v != null) p.set(k, v);
  const res = await fetch(`/api/${path}${p.toString() ? `?${p}` : ''}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ---------- Status ----------
function complianceStatus(pct) {
  const goal = state.meta?.sla_goal_pct ?? 90;
  if (pct == null) return 'neutral';
  pct = Math.round(pct * 10) / 10; // judge the value the reader sees
  if (pct >= goal) return 'good';
  if (pct >= goal - 5) return 'warning';
  return 'critical';
}
const STATUS_LABEL = { good: 'Meets goal', warning: 'Below goal', critical: 'Well below goal', neutral: 'No data' };
function statusPill(pct, label = true) {
  const s = complianceStatus(pct);
  return `<span class="pill ${s}">${ICON[s] || ''}${fmt.pct(pct)}${label ? ` · ${STATUS_LABEL[s]}` : ''}</span>`;
}

// ---------- Tooltip ----------
const tip = $('#tooltip');
function showTip(evt, title, rows) {
  tip.innerHTML = `<div class="tt-title">${esc(title)}</div>${rows.map(([label, value, color]) =>
    `<div class="tt-row"><span>${color ? `<span class="swatch" style="background:${color};display:inline-block"></span>` : ''}${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}`;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + 14;
  let y = evt.clientY + 14;
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - 14;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
const hideTip = () => { tip.hidden = true; };
function bindTips(root, lookup) {
  root.querySelectorAll('[data-tip]').forEach((node) => {
    const show = (e) => { const t = lookup(node.dataset.tip); if (t) showTip(e, t.title, t.rows); };
    node.addEventListener('mousemove', show);
    node.addEventListener('mouseleave', hideTip);
    node.addEventListener('focus', (e) => {
      const b = node.getBoundingClientRect();
      show({ clientX: b.left + b.width / 2, clientY: b.top });
    });
    node.addEventListener('blur', hideTip);
  });
}

// ---------- Chart helpers ----------
function niceMax(v) {
  if (v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= v) return m * mag;
  return 10 * mag;
}
function ticks(min, max, n = 4) { return Array.from({ length: n + 1 }, (_, i) => min + ((max - min) * i) / n); }
const color = (slot) => `var(--series-${slot})`;
// Charts are drawn at their panel's real width so text stays at its true size.
function chartWidth(kind = 'full') {
  const view = $('#view');
  const inner = view.clientWidth - (innerWidth <= 860 ? 32 : 48);
  const pad = 38;
  const wide = innerWidth > 1080;
  const w = { full: inner - pad, half: wide ? (inner - 16) / 2 - pad : inner - pad,
    main: wide ? ((inner - 16) * 1.6) / 2.6 - pad : inner - pad, side: wide ? (inner - 16) / 2.6 - pad : inner - pad }[kind];
  return Math.max(300, Math.floor(w));
}
function legend(items) {
  return `<div class="legend">${items.map(([label, c, kind]) =>
    `<span><span class="swatch ${kind || ''}" style="background:${c}"></span>${esc(label)}</span>`).join('')}</div>`;
}
function dataTable(columns, rows) {
  return `<details class="data"><summary>Show as table</summary><div class="table-wrap"><table><thead><tr>${columns.map(([, h, num]) =>
    `<th class="${num ? 'num' : ''}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) =>
    `<tr>${columns.map(([k, , num, f]) => `<td class="${num ? 'num' : ''}">${esc(f ? f(r[k], r) : r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}

// Vertical columns, one series.
function columnChart(rows, { x, y, label, fill = color(1), fmtY = fmt.int, tipRows, height = 240, xLabel = (v) => v, every = 1, width = 720 }) {
  const W = width; const H = height; const m = { t: 12, r: 8, b: 26, l: 46 };
  const max = niceMax(Math.max(...rows.map((r) => r[y]), 1));
  const iw = W - m.l - m.r; const ih = H - m.t - m.b;
  const step = iw / Math.max(rows.length, 1); const bw = Math.max(2, Math.min(28, step - 2));
  const sy = (v) => m.t + ih - (v / max) * ih;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  for (const t of ticks(0, max)) s += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${sy(t)}" y2="${sy(t)}"/><text class="tick" x="${m.l - 8}" y="${sy(t) + 3.5}" text-anchor="end">${fmtY(t)}</text>`;
  rows.forEach((r, i) => {
    const cx = m.l + step * i + step / 2; const top = sy(r[y]); const h = m.t + ih - top;
    if (h > 0) s += `<path d="M${cx - bw / 2},${m.t + ih} v${-Math.max(h - 3, 0)} q0,-3 3,-3 h${bw - 6} q3,0 3,3 v${Math.max(h - 3, 0)} z" fill="${fill}"/>`;
    s += `<rect class="hit" data-tip="${i}" tabindex="0" x="${m.l + step * i}" y="${m.t}" width="${step}" height="${ih}" aria-label="${esc(xLabel(r[x]))}: ${esc(fmtY(r[y]))}"/>`;
    if (i % every === 0) s += `<text class="tick" x="${cx}" y="${H - 8}" text-anchor="middle">${esc(xLabel(r[x]))}</text>`;
  });
  s += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/></svg>`;
  return { html: `<div class="chart chart-scroll">${s}</div>`, bind: (root) => bindTips(root, (i) => tipRows(rows[i])) };
}

// Lines over a shared x index, one y-scale, optional dashed reference line.
function lineChart(xs, series, { label, fmtY = fmt.int, yMin = 0, yMax, ref, xLabel = (v) => v, every = 1, height = 240, tipTitle = (v) => v, width = 720, extraTip }) {
  const W = width; const H = height; const m = { t: 14, r: 12, b: 26, l: 46 };
  const vals = series.flatMap((s) => s.values).filter((v) => v != null);
  const hi = yMax ?? niceMax(Math.max(...vals, ref?.value ?? 0));
  const lo = yMin;
  const iw = W - m.l - m.r; const ih = H - m.t - m.b;
  const sx = (i) => m.l + (xs.length < 2 ? iw / 2 : (i / (xs.length - 1)) * iw);
  const sy = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  for (const t of ticks(lo, hi)) s += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${sy(t)}" y2="${sy(t)}"/><text class="tick" x="${m.l - 8}" y="${sy(t) + 3.5}" text-anchor="end">${fmtY(t)}</text>`;
  xs.forEach((x, i) => { if (i % every === 0) s += `<text class="tick" x="${sx(i)}" y="${H - 8}" text-anchor="middle">${esc(xLabel(x))}</text>`; });
  if (ref) s += `<line class="ref" x1="${m.l}" x2="${W - m.r}" y1="${sy(ref.value)}" y2="${sy(ref.value)}"/><text class="ref-label" x="${W - m.r}" y="${sy(ref.value) - 5}" text-anchor="end">${esc(ref.label)}</text>`;
  for (const ser of series) {
    let d = ''; let pen = false;
    ser.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(Math.max(lo, Math.min(hi, v))).toFixed(1)}`; pen = true;
    });
    s += `<path d="${d}" fill="none" stroke="${ser.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  s += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
  s += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/><g class="dots"></g>`;
  s += `<rect class="hit overlay" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" tabindex="0" aria-label="${esc(label)}. Use arrow keys to read values."/></svg>`;
  const bind = (root) => {
    const svg = root.querySelector('svg'); const overlay = svg.querySelector('.overlay');
    const cross = svg.querySelector('.cross'); const dots = svg.querySelector('.dots');
    let idx = xs.length - 1;
    const place = (i, evt) => {
      idx = Math.max(0, Math.min(xs.length - 1, i));
      cross.setAttribute('x1', sx(idx)); cross.setAttribute('x2', sx(idx)); cross.setAttribute('visibility', 'visible');
      dots.innerHTML = series.map((ser) => (ser.values[idx] == null ? '' :
        `<circle cx="${sx(idx)}" cy="${sy(ser.values[idx])}" r="4.5" fill="${ser.color}" stroke="var(--surface)" stroke-width="2"/>`)).join('');
      showTip(evt, tipTitle(xs[idx]), [...series.map((ser) => [ser.name, fmtY(ser.values[idx]), ser.color]), ...(extraTip ? extraTip(idx) : [])]);
    };
    const clear = () => { cross.setAttribute('visibility', 'hidden'); dots.innerHTML = ''; hideTip(); };
    overlay.addEventListener('mousemove', (e) => {
      const b = svg.getBoundingClientRect(); const px = ((e.clientX - b.left) / b.width) * W;
      place(Math.round(((px - m.l) / iw) * (xs.length - 1)), e);
    });
    overlay.addEventListener('mouseleave', clear);
    overlay.addEventListener('blur', clear);
    overlay.addEventListener('keydown', (e) => {
      const jump = e.shiftKey ? 10 : 1;
      const map = { ArrowLeft: idx - jump, ArrowRight: idx + jump, Home: 0, End: xs.length - 1 };
      if (!(e.key in map)) return;
      e.preventDefault();
      const b = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(xs.length - 1, map[e.key]));
      place(i, { clientX: b.left + (sx(i) / W) * b.width, clientY: b.top + 20 });
    });
  };
  return { html: `<div class="chart chart-scroll">${s}</div>`, bind };
}

// Horizontal grouped bars: one row per label, one bar per series.
function hbarChart(rows, series, { label, fmtX = fmt.pct, max, highlight = new Set(), rowLabel = (r) => r.label, width = 720, labelWidth = 168 }) {
  const W = width; const bh = 11; const gap = 2; const groupH = series.length * bh + (series.length - 1) * gap;
  const rowH = groupH + 18; const m = { t: 6, r: 56, b: 6, l: labelWidth };
  const H = m.t + m.b + rows.length * rowH;
  const hi = max ?? niceMax(Math.max(...rows.flatMap((r) => series.map((s) => r[s.key] || 0)), 1));
  const iw = W - m.l - m.r; const sx = (v) => (v / hi) * iw;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  rows.forEach((r, i) => {
    const y0 = m.t + i * rowH + 9;
    const strong = highlight.has(rowLabel(r));
    s += `<text class="dlabel ${strong ? 'strong' : ''}" x="${m.l - 12}" y="${y0 + groupH / 2 + 4}" text-anchor="end" font-family="var(--sans)">${esc(rowLabel(r))}</text>`;
    series.forEach((ser, j) => {
      const y = y0 + j * (bh + gap); const w = Math.max(sx(r[ser.key] || 0), 0);
      if (w > 0) s += `<path d="M${m.l},${y} h${Math.max(w - 3, 0)} q3,0 3,3 v${bh - 6} q0,3 -3,3 h${-Math.max(w - 3, 0)} z" fill="${ser.color}"/>`;
      s += `<text class="dlabel" x="${m.l + w + 6}" y="${y + bh - 2}">${esc(fmtX(r[ser.key]))}</text>`;
    });
    s += `<rect class="hit" data-tip="${i}" tabindex="0" x="0" y="${y0 - 6}" width="${W}" height="${rowH}" aria-label="${esc(rowLabel(r))}: ${series.map((ser) => `${ser.name} ${fmtX(r[ser.key])}`).join(', ')}"/>`;
  });
  s += `<line class="axis" x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${H - m.b}"/></svg>`;
  return {
    html: `<div class="chart">${series.length > 1 ? legend(series.map((x) => [x.name, x.color])) : ''}${s}</div>`,
    bind: (root) => bindTips(root, (i) => ({ title: rowLabel(rows[i]), rows: series.map((ser) => [ser.name, fmtX(rows[i][ser.key]), ser.color]) })),
  };
}

// Category x priority heatmap, sequential blue with printed values.
function heatmap(rows, cats, prios, { label, width = 720, labelWidth = 168 }) {
  const W = width; const cellH = 34; const m = { t: 30, r: 4, b: 4, l: labelWidth };
  const cw = (W - m.l - m.r) / prios.length; const H = m.t + m.b + cats.length * cellH;
  const byKey = new Map(rows.map((r) => [`${r.category}|${r.priority}`, r]));
  const max = Math.max(...rows.map((r) => r.breach_rate_pct || 0), 1);
  const step = (v) => (v == null ? 0 : v < max * 0.25 ? 0 : v < max * 0.5 ? 1 : v < max * 0.75 ? 2 : 3);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  prios.forEach((p, j) => { s += `<text class="tick" x="${m.l + cw * j + cw / 2}" y="${m.t - 12}" text-anchor="middle">${esc(p)}</text>`; });
  cats.forEach((c, i) => {
    const y = m.t + i * cellH;
    s += `<text class="dlabel" x="${m.l - 12}" y="${y + cellH / 2 + 4}" text-anchor="end" font-family="var(--sans)">${esc(c)}</text>`;
    prios.forEach((p, j) => {
      const r = byKey.get(`${c}|${p}`); const v = r?.breach_rate_pct; const k = step(v);
      s += `<rect x="${m.l + cw * j + 1}" y="${y + 1}" width="${cw - 2}" height="${cellH - 2}" rx="3" fill="var(--seq-${k})"/>`;
      s += `<text x="${m.l + cw * j + cw / 2}" y="${y + cellH / 2 + 4}" text-anchor="middle" font-size="11.5" fill="var(--seq-ink-${k})">${v == null ? '–' : fmt.pct(v)}</text>`;
      s += `<rect class="hit" data-tip="${c}|${p}" tabindex="0" x="${m.l + cw * j}" y="${y}" width="${cw}" height="${cellH}" aria-label="${esc(c)}, ${esc(p)}: ${v == null ? 'no tickets' : fmt.pct(v)}"/>`;
    });
  });
  s += '</svg>';
  return {
    html: `<div class="chart chart-scroll">${s}</div>`,
    bind: (root) => bindTips(root, (key) => {
      const r = byKey.get(key); if (!r) return null;
      return { title: `${r.category} · ${r.priority}`, rows: [['Breach rate', fmt.pct(r.breach_rate_pct)], ['Breaches', fmt.int(r.breaches)], ['Tickets', fmt.int(r.tickets)]] };
    }),
  };
}

// ---------- Filter bar ----------
function renderFilterBar() {
  const f = state.filters; const meta = state.meta;
  const preset = PRESETS.find(([, , s, e]) => s === f.start && e === f.end)?.[0] ?? 'custom';
  let h = '<span class="label">Period</span><div class="segmented" role="group" aria-label="Period">';
  for (const [id, text] of PRESETS) h += `<button type="button" data-preset="${id}" aria-pressed="${preset === id}">${text}</button>`;
  h += '</div><div class="divider"></div><span class="label">Filter</span>';
  for (const [key, text, source] of DIMENSIONS) {
    const options = source === 'priorities' ? meta.priorities.map((p) => p.name) : meta[source];
    const n = f[key].length;
    h += `<div class="dropdown" data-dim="${key}"><button type="button" aria-haspopup="true" aria-expanded="false" class="${n ? 'active' : ''}">${text}${n ? ` <span class="count">${n}</span>` : ''}${ICON.chevron}</button>
      <div class="menu" hidden role="group" aria-label="${text}">${options.map((o) =>
        `<label><input type="checkbox" value="${esc(o)}" ${f[key].includes(o) ? 'checked' : ''}>${esc(o)}</label>`).join('')}
      <div class="menu-foot"><button type="button" class="linkish" data-clear="${key}">Clear</button><button type="button" class="linkish" data-close>Done</button></div></div></div>`;
  }
  const chips = DIMENSIONS.flatMap(([key, text]) => f[key].map((v) => [key, text, v]));
  if (chips.length) {
    h += `<div class="chips">${chips.map(([key, text, v]) =>
      `<span class="chip">${esc(text)}: ${esc(v)}<button type="button" aria-label="Remove ${esc(text)} ${esc(v)}" data-remove="${key}" data-value="${esc(v)}">×</button></span>`).join('')}
      <button type="button" class="linkish" data-clear-all>Clear all</button></div>`;
  }
  const bar = $('#filterbar'); bar.innerHTML = h;

  bar.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => {
    const p = PRESETS.find(([id]) => id === b.dataset.preset);
    f.start = p[2]; f.end = p[3]; changed();
  }));
  bar.querySelectorAll('.dropdown').forEach((dd) => {
    const btn = dd.querySelector('button'); const menu = dd.querySelector('.menu');
    const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = menu.hidden;
      bar.querySelectorAll('.menu').forEach((m) => { m.hidden = true; });
      bar.querySelectorAll('.dropdown > button').forEach((b) => b.setAttribute('aria-expanded', 'false'));
      menu.hidden = !open; btn.setAttribute('aria-expanded', String(open));
      if (open) menu.querySelector('input')?.focus();
    });
    menu.addEventListener('click', (e) => e.stopPropagation());
    menu.addEventListener('keydown', (e) => { if (e.key === 'Escape') { close(); btn.focus(); } });
    menu.querySelectorAll('input').forEach((i) => i.addEventListener('change', () => {
      f[dd.dataset.dim] = [...menu.querySelectorAll('input:checked')].map((x) => x.value);
      changed({ keepMenu: dd.dataset.dim });
    }));
    menu.querySelector('[data-close]').addEventListener('click', () => { close(); btn.focus(); });
    menu.querySelector('[data-clear]').addEventListener('click', () => { f[dd.dataset.dim] = []; changed(); });
  });
  bar.querySelectorAll('[data-remove]').forEach((b) => b.addEventListener('click', () => {
    f[b.dataset.remove] = f[b.dataset.remove].filter((v) => v !== b.dataset.value); changed();
  }));
  bar.querySelector('[data-clear-all]')?.addEventListener('click', () => {
    for (const [key] of DIMENSIONS) f[key] = []; changed();
  });
}
document.addEventListener('click', () => {
  document.querySelectorAll('#filterbar .menu').forEach((m) => { m.hidden = true; });
  document.querySelectorAll('#filterbar .dropdown > button').forEach((b) => b.setAttribute('aria-expanded', 'false'));
});

let debounce;
function changed({ keepMenu } = {}) {
  state.tickets.offset = 0;
  writeHash();
  renderFilterBar();
  if (keepMenu) {
    const dd = document.querySelector(`#filterbar .dropdown[data-dim="${keepMenu}"]`);
    dd.querySelector('.menu').hidden = false; dd.querySelector('button').setAttribute('aria-expanded', 'true');
  }
  clearTimeout(debounce);
  debounce = setTimeout(render, 120);
}

// ---------- Views ----------
function kpiStrip(k) {
  const s = complianceStatus(k.sla_compliance_pct);
  const r = complianceStatus(k.response_compliance_pct);
  const goal = state.meta.sla_goal_pct;
  return `<section class="kpis" aria-label="Key indicators">
    <div class="kpi"><span class="k-label">Tickets</span><strong class="k-value">${fmt.int(k.total_tickets)}</strong><div class="k-sub">${fmt.int(k.sla_breaches)} breached SLA</div></div>
    <div class="kpi"><span class="k-label">SLA compliance</span><strong class="k-value">${fmt.pct(k.sla_compliance_pct)}</strong><div class="k-sub"><span class="status ${s}">${ICON[s] || ''}${STATUS_LABEL[s]}</span> · goal ${goal}%</div></div>
    <div class="kpi"><span class="k-label">First response on time</span><strong class="k-value">${fmt.pct(k.response_compliance_pct)}</strong><div class="k-sub"><span class="status ${r}">${ICON[r] || ''}${STATUS_LABEL[r]}</span></div></div>
    <div class="kpi"><span class="k-label">Resolution time</span><strong class="k-value">${fmt.hours(k.median_resolution_hours)}</strong><div class="k-sub">median · 90th pct ${fmt.hours(k.p90_resolution_hours)}</div></div>
    <div class="kpi"><span class="k-label">Open backlog</span><strong class="k-value">${fmt.int(k.open_backlog)}</strong><div class="k-sub">${fmt.int(k.open_breached)} already past target</div></div>
    <div class="kpi"><span class="k-label">Reassigned</span><strong class="k-value">${fmt.pct(k.reassigned_pct)}</strong><div class="k-sub">reopened ${fmt.pct(k.reopened_pct)}</div></div>
  </section>`;
}

function panel(title, sub, body, { flush = false, tools = '' } = {}) {
  return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2>${sub ? `<p>${sub}</p>` : ''}</div>${tools}</div><div class="panel-body ${flush ? 'flush' : ''}">${body}</div></section>`;
}

async function viewOverview(root) {
  const d = await api('overview');
  if (!d.kpis.total_tickets) { root.innerHTML = '<div class="empty">No tickets match these filters.</div>'; return; }
  const months = d.monthly.map((r) => r.opened_month);
  const half = chartWidth('half');
  const every = Math.max(1, Math.ceil(months.length / Math.floor(half / 64)));
  const vol = columnChart(d.monthly, {
    x: 'opened_month', y: 'tickets_opened', label: 'Tickets opened per month', xLabel: fmt.monthShort, every, width: half,
    tipRows: (r) => ({ title: fmt.month(r.opened_month), rows: [['Tickets opened', fmt.int(r.tickets_opened)], ['SLA breaches', fmt.int(r.sla_breaches)]] }),
  });
  const comp = lineChart(months, [
    { name: 'Resolution SLA', values: d.monthly.map((r) => r.sla_compliance_pct), color: color(1) },
    { name: 'First response', values: d.monthly.map((r) => r.response_compliance_pct), color: color(2) },
  ], { label: 'SLA compliance by month', fmtY: (v) => fmt.pct(v, 0), yMin: 60, yMax: 100, ref: { value: state.meta.sla_goal_pct, label: `Goal ${state.meta.sla_goal_pct}%` }, xLabel: fmt.monthShort, every, tipTitle: fmt.month, width: half });
  const bl = d.backlog;
  const days = bl.map((r) => r.flow_date);
  const avg7 = bl.map((_, i) => {
    const w = bl.slice(Math.max(0, i - 6), i + 1);
    return Math.round((w.reduce((a, r) => a + r.backlog, 0) / w.length) * 10) / 10;
  });
  const mainW = chartWidth('main');
  const backlog = lineChart(days, [{ name: '7-day average', values: avg7, color: color(1) }], {
    label: 'Open backlog, 7-day average', xLabel: (v) => fmt.monthShort(v.slice(0, 7)), every: Math.max(1, Math.ceil(days.length / Math.floor(mainW / 80))), tipTitle: fmt.day, width: mainW,
    extraTip: (i) => [['Open that day', fmt.int(bl[i].backlog)], ['Opened', fmt.int(bl[i].opened)], ['Resolved', fmt.int(bl[i].resolved)]],
  });
  const aging = hbarChart(d.aging, [
    { key: 'open_tickets', name: 'Open', color: color(1) },
    { key: 'already_breached', name: 'Already past target', color: color(2) },
  ], { label: 'Open tickets by age', fmtX: fmt.int, rowLabel: (r) => r.age_band, width: chartWidth('side'), labelWidth: 96 });
  const prioRows = d.priority.map((p) => `<tr><td><b>${esc(p.priority_code)}</b> ${esc(p.priority)}</td><td class="num">${fmt.hours(p.response_target_hours)}</td><td class="num">${fmt.hours(p.resolution_target_hours)}</td><td class="num">${fmt.int(p.tickets)}</td><td class="num">${fmt.int(p.breaches)}</td><td class="num">${fmt.hours(p.avg_resolution_hours)}</td><td class="num">${fmt.pct(p.response_compliance_pct)}</td><td class="num">${statusPill(p.sla_compliance_pct, false)}</td></tr>`).join('');

  root.innerHTML = `${kpiStrip(d.kpis)}
    <div class="grid cols-2 section-gap">
      ${panel('Tickets opened per month', 'Spikes line up with a VPN outage (Feb 2025), the Windows 11 migration (Sep 2025) and an MFA roll-out (Mar 2026).', vol.html + dataTable([['opened_month', 'Month', false, fmt.month], ['tickets_opened', 'Tickets', true, fmt.int], ['sla_breaches', 'Breaches', true, fmt.int]], d.monthly))}
      ${panel('SLA compliance by month', 'Share of scored tickets that met their priority target, by the month they were opened.', legend([['Resolution SLA', color(1), 'line'], ['First response', color(2), 'line'], [`Goal ${state.meta.sla_goal_pct}%`, 'transparent', 'dash']]) + comp.html + dataTable([['opened_month', 'Month', false, fmt.month], ['sla_compliance_pct', 'Resolution SLA', true, (v) => fmt.pct(v)], ['response_compliance_pct', 'First response', true, (v) => fmt.pct(v)]], d.monthly))}
    </div>
    <div class="grid cols-main section-gap">
      ${panel('Open backlog', 'Tickets still open at the end of each day (running total of opened minus resolved), smoothed over 7 days.', backlog.html)}
      ${panel('Age of the open backlog', `At the snapshot, ${fmt.int(d.kpis.open_backlog)} tickets were open and ${fmt.int(d.kpis.open_breached)} of them already past target.`, aging.html + dataTable([['age_band', 'Age', false], ['open_tickets', 'Open', true, fmt.int], ['already_breached', 'Past target', true, fmt.int]], d.aging))}
    </div>
    <div class="section-gap">${panel('Performance against each priority target', 'Response and resolution targets in calendar hours, 24x7.', `<div class="table-wrap"><table><thead><tr><th>Priority</th><th class="num">Response target</th><th class="num">Resolution target</th><th class="num">Tickets</th><th class="num">Breaches</th><th class="num">Avg resolution</th><th class="num">Response on time</th><th class="num">Resolution SLA</th></tr></thead><tbody>${prioRows}</tbody></table></div>`, { flush: true })}</div>`;
  const panels = root.querySelectorAll('.chart');
  vol.bind(panels[0].parentElement); comp.bind(panels[1].parentElement);
  backlog.bind(panels[2].parentElement); aging.bind(panels[3].parentElement);
}

async function viewBreaches(root) {
  const d = await api('breaches');
  if (!d.kpis.sla_breaches) { root.innerHTML = '<div class="empty">No SLA breaches match these filters.</div>'; return; }
  if (!d.top_categories) { root.innerHTML = '<div class="empty">Breach concentration compares categories: widen the Category filter to at least two.</div>'; return; }
  const top = new Set(d.top_categories);
  const share = hbarChart(d.pareto, [
    { key: 'share_of_volume_pct', name: 'Share of tickets', color: color(1) },
    { key: 'share_of_breaches_pct', name: 'Share of SLA breaches', color: color(2) },
  ], { label: 'Share of ticket volume and of SLA breaches by category', highlight: top, width: chartWidth('main') });
  const cats = state.meta.categories.filter((c) => d.pareto.some((p) => p.label === c));
  const prios = state.meta.priorities.map((p) => p.name).filter((p) => d.matrix.some((r) => r.priority === p));
  const heat = heatmap(d.matrix, d.pareto.map((p) => p.label).filter((c) => cats.includes(c)), prios, { label: 'Breach rate by category and priority', width: chartWidth('side'), labelWidth: 150 });

  const driverCharts = d.top_categories.map((cat) => {
    const rows = ['0 hops', '1 hop', '2+ hops'].map((hop) => {
      const pick = (w) => d.drivers.find((r) => r.category === cat && r.hop_bucket === hop && r.waited_on_third_party === w);
      return { label: hop === '0 hops' ? 'Kept by first group' : hop === '1 hop' ? 'Handed off once' : 'Handed off 2+ times', no_wait: pick(0)?.breach_rate_pct ?? null, waited: pick(1)?.breach_rate_pct ?? null, n0: pick(0)?.tickets ?? 0, n1: pick(1)?.tickets ?? 0 };
    });
    const f = d.focus.find((x) => x.category === cat);
    return { cat, f, chart: hbarChart(rows, [
      { key: 'no_wait', name: 'No third-party wait', color: color(1) },
      { key: 'waited', name: f.wait_reason, color: color(2) },
    ], { label: `${cat}: breach rate by hand-offs and third-party wait`, max: 100, width: chartWidth('half'), labelWidth: 150 }) };
  });

  const rows = d.pareto.map((r) => `<tr class="${top.has(r.label) ? 'flag' : ''}"><td class="num">${r.breach_rank}</td><td>${esc(r.label)}</td><td class="num">${fmt.int(r.tickets)}</td><td class="num">${fmt.int(r.breaches)}</td><td class="num">${fmt.pct(r.breach_rate_pct)}</td><td class="num">${fmt.pct(r.share_of_volume_pct)}</td><td class="num">${fmt.pct(r.share_of_breaches_pct)}</td><td class="num">${fmt.pct(r.cumulative_share_pct)}</td></tr>`).join('');
  const subs = d.subcategories.slice(0, 10).map((s) => `<tr><td>${esc(s.subcategory)}</td><td class="muted">${esc(s.category)}</td><td class="num">${fmt.int(s.tickets)}</td><td class="num">${fmt.int(s.breaches)}</td><td class="num">${fmt.pct(s.breach_rate_pct)}</td><td class="num">${fmt.hours(s.avg_resolution_hours)}</td></tr>`).join('');
  const wi = d.what_if || {};
  const recs = d.recommendations.map((r, i) => `<article class="rec"><span class="n">RECOMMENDATION ${i + 1}</span><h3>${esc(r.title)}</h3><p><b>Evidence.</b> ${esc(r.evidence)}</p><p><b>Action.</b> ${esc(r.action)}</p><span class="owner">Owner · ${esc(r.owner)}</span></article>`).join('');

  root.innerHTML = `<section class="readout" aria-label="Finding">
      <h2>Finding</h2>
      <p class="headline">${esc(d.headline)}</p>
      <dl style="margin-top:14px">
        <dt>Concentration</dt><dd>${esc(d.top_categories[0])} and ${esc(d.top_categories[1])} breach ${fmt.pct(wi.focus_breach_rate_pct)} of scored tickets; the other six categories together breach ${fmt.pct(wi.rest_breach_rate_pct)}.</dd>
        <dt>Mechanism</dt><dd>Both queues depend on someone outside the desk and pass tickets between groups more often. ${d.focus.map((f) => `${fmt.pct(f.share_of_breaches_waited_pct, 0)} of ${esc(f.category)} breaches were ${esc(f.wait_reason.toLowerCase())}`).join('; ')}.</dd>
        <dt>Upside</dt><dd>At the rest of the desk's breach rate, about ${fmt.int(wi.breaches_avoided)} breaches disappear and compliance moves from ${fmt.pct(wi.current_compliance_pct)} to ${fmt.pct(wi.what_if_compliance_pct)}.</dd>
      </dl>
    </section>
    <div class="grid cols-main section-gap">
      ${panel('Share of tickets vs share of breaches', 'A category above its volume share breaches more than its size explains.', share.html)}
      ${panel('Breach rate by category and priority', 'Share of scored tickets that breached. Stronger colour is worse; hover a cell for its ticket count.', heat.html)}
    </div>
    <div class="section-gap">${panel('Breach Pareto', 'Categories ranked by breach count, with the cumulative share. The two flagged rows are the focus of the recommendations.', `<div class="table-wrap"><table><thead><tr><th class="num">Rank</th><th>Category</th><th class="num">Tickets</th><th class="num">Breaches</th><th class="num">Breach rate</th><th class="num">Share of tickets</th><th class="num">Share of breaches</th><th class="num">Cumulative</th></tr></thead><tbody>${rows}</tbody></table></div>`, { flush: true })}</div>
    <div class="grid cols-2 section-gap">
      ${driverCharts.map((x) => panel(`${esc(x.cat)}: what sits behind a breach`, `Breach rate by how many times the ticket changed groups, split by whether it waited on a third party (${esc(x.f.wait_reason.toLowerCase())}).`, x.chart.html)).join('')}
    </div>
    <div class="section-gap">${panel('Worst subcategories in the two focus categories', 'Ranked by breach count.', `<div class="table-wrap"><table><thead><tr><th>Subcategory</th><th>Category</th><th class="num">Tickets</th><th class="num">Breaches</th><th class="num">Breach rate</th><th class="num">Avg resolution</th></tr></thead><tbody>${subs}</tbody></table></div>`, { flush: true })}</div>
    <h2 class="sr-only">Recommendations</h2>
    <div class="recs section-gap">${recs}</div>`;
  const charts = root.querySelectorAll('.chart');
  share.bind(charts[0].parentElement); heat.bind(charts[1].parentElement);
  driverCharts.forEach((x, i) => x.chart.bind(charts[2 + i].parentElement));
}

async function viewQueues(root) {
  const [d, agents] = await Promise.all([api('overview'), api('agents')]);
  const maxT = Math.max(...d.groups.map((g) => g.tickets), 1);
  const groups = d.groups.map((g) => `<tr><td>${esc(g.assignment_group)}</td><td class="num"><div class="bar-cell">${fmt.int(g.tickets)}<i style="width:${Math.round((g.tickets / maxT) * 80)}px"></i></div></td><td class="num">${fmt.int(g.open_tickets)}</td><td class="num">${fmt.int(g.breaches)}</td><td class="num">${fmt.hours(g.avg_resolution_hours)}</td><td class="num">${Number(g.avg_reassignments).toFixed(2)}</td><td class="num">${statusPill(g.sla_compliance_pct, false)}</td></tr>`).join('');
  const ag = agents.map((a) => `<tr><td>${esc(a.assigned_agent)}</td><td class="muted">${esc(a.assignment_group)}</td><td class="num">${fmt.int(a.tickets)}</td><td class="num">${fmt.int(a.open_tickets)}</td><td class="num">${fmt.int(a.breaches)}</td><td class="num">${fmt.hours(a.avg_resolution_hours)}</td><td class="num">${statusPill(a.sla_compliance_pct, false)}</td></tr>`).join('');
  root.innerHTML = `${panel('Resolver groups', 'Avg hand-offs counts how many times a ticket moved between groups before it was resolved.', `<div class="table-wrap"><table><thead><tr><th>Group</th><th class="num">Tickets</th><th class="num">Open</th><th class="num">Breaches</th><th class="num">Avg resolution</th><th class="num">Avg hand-offs</th><th class="num">SLA compliance</th></tr></thead><tbody>${groups}</tbody></table></div>`, { flush: true })}
    <div class="section-gap">${panel('Agent scorecard', 'Compliance is driven by the queue an agent works, not the agent: compare agents only within a group.', `<div class="table-wrap"><table><thead><tr><th>Agent</th><th>Group</th><th class="num">Tickets</th><th class="num">Open</th><th class="num">Breaches</th><th class="num">Avg resolution</th><th class="num">SLA compliance</th></tr></thead><tbody>${ag}</tbody></table></div>`, { flush: true })}</div>`;
}

const DQ_ACTION = { removed: 'neutral', repaired: 'good', quarantined: 'warning' };
async function viewQuality(root) {
  const d = await api('quality');
  const checks = d.checks.map((c) => `<tr><td class="mono">${esc(c.id)}</td><td><span class="dim-tag">${esc(c.dimension)}</span></td><td><b>${esc(c.name)}</b><div class="muted">${esc(c.rule)}</div></td><td><span class="pill ${DQ_ACTION[c.action]}">${esc(c.action)}</span></td><td class="num">${fmt.int(c.rows)}</td><td>${c.examples.slice(0, 3).map((e) => `<code class="raw">${esc(e)}</code>`).join(' ')}</td></tr>`).join('');
  const reasons = [...new Set(d.quarantine.map((q) => q.dq_reason))];
  const repaired = d.repaired_breakdown.map((r) => `<tr><td>${esc(r.repair)}</td><td class="num">${fmt.int(r.tickets)}</td></tr>`).join('');
  root.innerHTML = `<section class="funnel" aria-label="Quality gate totals">
      <div class="kpi"><span class="k-label">Rows exported</span><strong class="k-value">${fmt.int(d.rows_in)}</strong><div class="k-sub">raw ITSM export</div></div>
      <div class="kpi"><span class="k-label">Removed</span><strong class="k-value">${fmt.int(d.rows_removed)}</strong><div class="k-sub">duplicates and stale versions</div></div>
      <div class="kpi"><span class="k-label">Repaired</span><strong class="k-value">${fmt.int(d.rows_repaired)}</strong><div class="k-sub">fixed by a deterministic rule</div></div>
      <div class="kpi"><span class="k-label">Quarantined</span><strong class="k-value">${fmt.int(d.rows_quarantined)}</strong><div class="k-sub">held out of every SLA number</div></div>
      <div class="kpi"><span class="k-label">Clean tickets</span><strong class="k-value">${fmt.int(d.rows_clean)}</strong><div class="k-sub">loaded to the reporting layer</div></div>
    </section>
    <div class="section-gap">${panel('Checks', 'Run in order on every load: uniqueness, then label consistency, then completeness, then timeline validity. Results are also written to the dq_check_results table.', `<div class="table-wrap"><table><thead><tr><th>Check</th><th>Dimension</th><th>Rule</th><th>Action</th><th class="num">Rows</th><th>Examples</th></tr></thead><tbody>${checks}</tbody></table></div>`, { flush: true })}</div>
    <div class="grid cols-main section-gap">
      ${panel('Quarantine', 'Records held back with the reason, for the owning team to correct at source.', `<div class="tools" style="padding:0 18px 10px"><label class="sr-only" for="q-reason">Reason</label><select id="q-reason"><option value="">All reasons (${fmt.int(d.quarantine.length)})</option>${reasons.map((r) => `<option>${esc(r)}</option>`).join('')}</select></div><div class="table-wrap" id="q-table"></div>`, { flush: true })}
      ${panel('Repairs applied', 'Tickets kept in reporting after a rule fixed them. Each carries its repair in dq_repaired.', `<div class="table-wrap"><table><thead><tr><th>Repair</th><th class="num">Tickets</th></tr></thead><tbody>${repaired}</tbody></table></div>`, { flush: true })}
    </div>`;
  const draw = () => {
    const reason = $('#q-reason', root).value;
    const rows = d.quarantine.filter((q) => !reason || q.dq_reason === reason).slice(0, 60);
    $('#q-table', root).innerHTML = `<table><thead><tr><th>Ticket</th><th>Reason</th><th>Opened</th><th>Resolved</th><th>Status</th><th>Priority</th></tr></thead><tbody>${rows.map((q) => `<tr><td class="mono">${esc(q.ticket_id)}</td><td>${esc(q.dq_reason)}</td><td class="mono">${esc(q.raw_record.opened_at) || '<span class="muted">blank</span>'}</td><td class="mono">${esc(q.raw_record.resolved_at) || '<span class="muted">blank</span>'}</td><td>${esc(q.raw_record.status)}</td><td>${esc(q.raw_record.priority) || '<span class="muted">blank</span>'}</td></tr>`).join('')}</tbody></table>`;
  };
  $('#q-reason', root).addEventListener('change', draw);
  draw();
}

const TICKET_COLS = [
  ['ticket_id', 'Ticket', 'ticket_id'], ['opened_at', 'Opened', 'opened_at'], ['priority', 'Priority', 'priority_order'],
  ['category', 'Category', 'category'], ['subcategory', 'Subcategory', null], ['assignment_group', 'Group', 'assignment_group'],
  ['reassignment_count', 'Hand-offs', 'reassignment_count'], ['elapsed_hours', 'Elapsed', 'elapsed_hours'], ['sla_state', 'SLA', 'sla_state'],
];
const STATE_PILL = { Met: 'good', Breached: 'critical', 'Open - breached': 'critical', 'Open - within SLA': 'neutral' };
async function viewTickets(root) {
  const t = state.tickets;
  const d = await api('tickets', { state: t.state, search: t.search, sort: t.sort, desc: t.desc, offset: t.offset, limit: 50 });
  const csv = new URLSearchParams(filterParams());
  if (t.state) csv.set('state', t.state);
  if (t.search) csv.set('search', t.search);
  const head = TICKET_COLS.map(([k, label, sortKey]) => {
    const sorted = sortKey && t.sort === sortKey;
    const aria = sorted ? ` aria-sort="${t.desc ? 'descending' : 'ascending'}"` : '';
    const num = ['reassignment_count', 'elapsed_hours'].includes(k) ? ' class="num"' : '';
    return `<th${num}${aria}>${sortKey ? `<button type="button" data-sort="${sortKey}">${label}</button>` : label}</th>`;
  }).join('');
  const body = d.rows.map((r) => `<tr><td class="mono">${esc(r.ticket_id)}</td><td class="mono">${esc(r.opened_at.slice(0, 16))}</td><td>${esc(r.priority)}</td><td>${esc(r.category)}</td><td>${esc(r.subcategory)}${r.wait_reason ? `<div class="muted">${esc(r.wait_reason)}</div>` : ''}</td><td>${esc(r.assignment_group)}<div class="muted">${esc(r.assigned_agent)}</div></td><td class="num">${r.reassignment_count}</td><td class="num">${fmt.hours(r.elapsed_hours)}<div class="muted">target ${fmt.hours(r.resolution_target_hours)}</div></td><td><span class="pill ${STATE_PILL[r.sla_state]}">${STATE_PILL[r.sla_state] === 'good' ? ICON.good : STATE_PILL[r.sla_state] === 'critical' ? ICON.critical : ''}${esc(r.sla_state)}</span>${r.dq_repaired ? `<div class="muted" title="Repaired by the quality gate">${esc(r.dq_repaired)}</div>` : ''}</td></tr>`).join('');
  const from = d.total ? t.offset + 1 : 0; const to = Math.min(t.offset + 50, d.total);
  root.innerHTML = panel('Tickets', 'Quality-gated tickets with their SLA outcome. Sort any column; export what you see as CSV.', `
    <div class="tools" style="padding:0 18px 12px">
      <label class="sr-only" for="t-search">Search</label><input type="search" id="t-search" placeholder="Ticket, subcategory or agent" value="${esc(t.search)}">
      <label class="sr-only" for="t-state">SLA outcome</label><select id="t-state"><option value="">All SLA outcomes</option>${state.meta.sla_states.map((s) => `<option ${s === t.state ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>
      <a class="button small" href="/api/tickets.csv?${csv}" download><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>Export CSV</a>
    </div>
    <div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body || '<tr><td colspan="9" class="empty">No tickets match.</td></tr>'}</tbody></table></div>
    <div class="pager"><span>${fmt.int(from)}–${fmt.int(to)} of ${fmt.int(d.total)}</span><div class="btns"><button class="button small" id="prev" ${t.offset ? '' : 'disabled'}>Previous</button><button class="button small" id="next" ${to < d.total ? '' : 'disabled'}>Next</button></div></div>`, { flush: true });
  root.querySelectorAll('[data-sort]').forEach((b) => b.addEventListener('click', () => {
    if (t.sort === b.dataset.sort) t.desc = !t.desc; else { t.sort = b.dataset.sort; t.desc = true; }
    t.offset = 0; render();
  }));
  let timer;
  $('#t-search', root).addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { t.search = e.target.value.trim(); t.offset = 0; render({ focus: '#t-search' }); }, 250); });
  $('#t-state', root).addEventListener('change', (e) => { t.state = e.target.value; t.offset = 0; render({ focus: '#t-state' }); });
  $('#prev', root).addEventListener('click', () => { t.offset = Math.max(0, t.offset - 50); render(); });
  $('#next', root).addEventListener('click', () => { t.offset += 50; render(); });
}

const RENDER = { overview: viewOverview, breaches: viewBreaches, queues: viewQueues, quality: viewQuality, tickets: viewTickets };

async function render({ focus } = {}) {
  const seq = ++state.seq;
  const v = VIEWS[state.view];
  $('#view-title').textContent = v.title;
  $('#view-subtitle').textContent = v.subtitle;
  document.title = `${v.title} · Service Ops & SLA Analytics`;
  document.querySelectorAll('#nav a').forEach((a) => {
    if (a.dataset.view === state.view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#filterbar').hidden = state.view === 'quality';
  const root = document.createElement('div');
  try {
    await RENDER[state.view](root);
  } catch (err) {
    root.innerHTML = `<div class="empty">Could not load this view (${esc(err.message)}). The free instance may still be waking up; try again in a moment.</div>`;
  }
  if (seq !== state.seq) return;
  hideTip();
  const view = $('#view');
  view.replaceChildren(...root.childNodes);
  if (focus) { const el = $(focus); if (el) { el.focus(); if (el.setSelectionRange && el.value) el.setSelectionRange(el.value.length, el.value.length); } }
}

// ---------- Shell ----------
function setupShell() {
  const btn = $('#theme-button');
  const sync = () => {
    const light = document.documentElement.dataset.theme === 'light';
    btn.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
  };
  btn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('serviceops.theme', next); } catch (e) { /* ignore */ }
    sync();
  });
  sync();
  const sidebar = $('#sidebar'); const scrim = $('#scrim'); const menu = $('#menu-button');
  const setNav = (open) => { sidebar.classList.toggle('open', open); scrim.hidden = !open; menu.setAttribute('aria-expanded', String(open)); };
  menu.addEventListener('click', () => setNav(!sidebar.classList.contains('open')));
  scrim.addEventListener('click', () => setNav(false));
  $('#nav').addEventListener('click', (e) => {
    const a = e.target.closest('a[data-view]'); if (!a) return;
    e.preventDefault(); setNav(false);
    state.view = a.dataset.view; writeHash(); render(); $('#view').focus({ preventScroll: true });
  });
  addEventListener('hashchange', () => { readHash(); renderFilterBar(); render(); });
  let lastW = innerWidth; let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (Math.abs(innerWidth - lastW) > 40) { lastW = innerWidth; render(); } }, 200);
  });
}

async function main() {
  readHash();
  setupShell();
  try {
    state.meta = await (await fetch('/api/meta')).json();
  } catch (err) {
    $('#view').innerHTML = '<div class="empty">The service is starting up. Refresh in a moment.</div>';
    return;
  }
  renderFilterBar();
  render();
}
main();
