const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const dur = s => s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : '';

const state = { q: '', tab: 'songs', page: 1, items: [], more: false, view: null, history: [] };

// ---- LCD status ----
function lcd(text, mode = '') {
  $('#lcd-text').textContent = text.toUpperCase();
  $('#lcd').className = 'lcd ' + mode;
}

async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const data = await r.json();
  if (!r.ok || data.error) throw new Error(data.error || r.statusText);
  return data;
}

// ---- rendering ----
function badges(it) {
  return (it.sources || []).map(s => `<span class="badge ${s}">${s === 'ytm' ? 'YTM' : 'YT'}</span>`).join('');
}

function thumb(it) {
  return it.thumb ? `<img src="${esc(it.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<span class="noimg"></span>';
}

function songRow(it, i, { check, preselect } = {}) {
  const sub = [it.artist, it.album].filter(Boolean).join(' · ');
  const lead = check ? `<input type="checkbox" data-i="${i}" ${preselect && !it.have ? 'checked' : ''} aria-label="Select ${esc(it.title)}">` : `<span class="n">${i + 1}.</span>`;
  return `<div class="row">
    ${lead}${thumb(it)}
    <div class="meta"><div class="t">${esc(it.title)}</div><div class="s">${esc(sub)}</div></div>
    <div class="act">${badges(it)}${it.have ? '<span class="have" title="Already in your library">&#10003;</span>' : ''}
      <span class="dur">${dur(it.duration)}</span>
      <a class="ext" href="${esc(it.url)}" target="_blank" rel="noopener" title="Preview on YouTube">&#8599;</a>
      <button class="dl" data-dl="${i}" title="Download">&#8595;</button></div>
  </div>`;
}

function collRow(it, i) {
  const sub = [it.type, it.artist, it.year].filter(Boolean).join(' · ');
  return `<div class="row click ${it.kind}" data-open="${i}" tabindex="0">
    <span class="n">${i + 1}.</span>${thumb(it)}
    <div class="meta"><div class="t">${esc(it.title)}</div><div class="s">${esc(sub)}</div></div>
    <div class="act">${badges(it)}<a class="ext" href="${esc(it.url)}" target="_blank" rel="noopener" title="Open on YouTube">&#8599;</a>&#9656;</div>
  </div>`;
}

function renderResults() {
  const el = $('#results');
  if (!state.items.length) { el.innerHTML = `<p class="empty">${state.q ? 'No results.' : 'Type something and hit GO.'}</p>`; return; }
  el.innerHTML = state.items.map((it, i) => it.kind === 'song' ? songRow(it, i) : collRow(it, i)).join('')
    + (state.more ? '<button class="btn more" id="more">MORE&hellip;</button>' : '');
  el.onclick = e => {
    const dl = e.target.closest('[data-dl]');
    if (dl) return download([state.items[+dl.dataset.dl]]);
    if (e.target.closest('a')) return;
    const row = e.target.closest('[data-open]');
    if (row) return openColl(state.items[+row.dataset.open]);
    if (e.target.id === 'more') { state.page++; runSearch(); }
  };
}

function renderColl() {
  const c = state.view, el = $('#results');
  const sub = [c.kind.toUpperCase(), c.kind !== 'artist' && c.artist, c.year, c.tracks && `${c.tracks.length} tracks`].filter(Boolean).join(' · ');
  let html = `<div class="coll-head">
    <button class="btn" id="back" title="Back">&#9664;</button>${thumb(c)}
    <div><div class="t">${esc(c.title)}</div><div class="s">${esc(sub)}</div>
    <div class="bar">${c.tracks?.length ? `<button class="btn primary" id="dl-sel">DOWNLOAD SELECTED</button>
      <button class="btn" id="sel-all">ALL</button><button class="btn" id="sel-none">NONE</button>` : ''}</div></div></div>`;
  if (c.kind === 'artist') html += '<div class="section-title">SONGS</div>';
  // artist pages start unticked: one click shouldn't queue a whole discography
  html += (c.tracks || []).map((t, i) => songRow(t, i, { check: true, preselect: c.kind !== 'artist' })).join('');
  if (c.albums?.length) html += '<div class="section-title">ALBUMS &amp; SINGLES</div>' + c.albums.map(collRow).join('');
  el.innerHTML = html;
  el.scrollTop = 0;
  const boxes = () => [...el.querySelectorAll('input[type=checkbox]')];
  const countSel = () => { const b = $('#dl-sel'); if (b) { const n = boxes().filter(x => x.checked).length; b.textContent = `DOWNLOAD SELECTED (${n})`; b.disabled = !n; } };
  countSel();
  el.onclick = e => {
    if (e.target.id === 'back') return back();
    if (e.target.id === 'sel-all' || e.target.id === 'sel-none') { boxes().forEach(b => b.checked = e.target.id === 'sel-all'); return countSel(); }
    if (e.target.id === 'dl-sel') return download(boxes().filter(b => b.checked).map(b => c.tracks[+b.dataset.i]), c);
    if (e.target.matches('input[type=checkbox]')) return countSel();
    const dl = e.target.closest('[data-dl]');
    if (dl) return download([c.tracks[+dl.dataset.dl]], c);
    if (e.target.closest('a')) return;
    const row = e.target.closest('[data-open]');
    if (row) return openColl(c.albums[+row.dataset.open]);
  };
}

function render() { state.view ? renderColl() : renderResults(); }

// ---- actions ----
const sources = () => ({ ytm: $('#src-ytm').checked, yt: $('#src-yt').checked });

async function runSearch() {
  const { ytm, yt } = sources();
  if (!ytm && !yt) return lcd('enable a source', 'err');
  lcd(`searching ${state.tab}: ${state.q}`, 'busy');
  try {
    const p = new URLSearchParams({ q: state.q, tab: state.tab, page: state.page, ytm: +ytm, yt: +yt });
    const r = await api('/api/search?' + p);
    state.items = r.items; state.more = r.more; state.view = null; state.history = [];
    render();
    lcd(`${r.items.length} ${state.tab} · ${state.q}`);
  } catch (e) { lcd(e.message, 'err'); }
}

async function openColl(it) {
  lcd(`loading ${it.kind}: ${it.title || ''}`, 'busy');
  try {
    const c = await api(`/api/open?kind=${it.kind}&id=${encodeURIComponent(it.id)}`);
    if (state.view) state.history.push(state.view);
    state.view = c;
    render();
    lcd(`${c.kind} · ${c.title}`);
  } catch (e) { lcd(e.message, 'err'); }
}

async function openUrl(url) {
  lcd('resolving link', 'busy');
  try {
    const r = await api('/api/open?url=' + encodeURIComponent(url));
    state.history = [];
    if (r.open) { state.view = r.open; lcd(`${r.open.kind} · ${r.open.title}`); }
    else { state.view = null; state.items = r.items; state.more = false; lcd('link resolved'); }
    render();
  } catch (e) { lcd(e.message, 'err'); }
}

function back() {
  state.view = state.history.pop() || null;
  render();
  lcd(state.view ? `${state.view.kind} · ${state.view.title}` : 'ready');
}

async function download(tracks, coll) {
  if (!tracks.length) return;
  // artist pages are not an album/playlist: their songs file as singles
  const collection = coll && coll.kind !== 'artist' ? { kind: coll.kind, title: coll.title, artist: coll.artist } : null;
  try {
    await api('/api/download', { format: $('#format').value, tracks: tracks.map(t => ({ ...t, collection })) });
    lcd(`queued ${tracks.length} track${tracks.length > 1 ? 's' : ''}`);
    poll();
  } catch (e) { lcd(e.message, 'err'); }
}

// ---- queue polling ----
const STATUS = { queued: 'WAITING', downloading: 'DOWNLOADING', converting: 'CONVERTING', done: 'DONE', skipped: 'SKIPPED', error: 'FAILED' };
let settingsLoaded = false, pollTimer;

async function poll() {
  clearTimeout(pollTimer);
  try {
    const s = await api('/api/state');
    if (!settingsLoaded) {
      $('#library').value = s.settings.library;
      $('#format').value = s.settings.format;
      settingsLoaded = true;
    }
    const jobs = s.jobs.slice().reverse();
    $('#jobs').innerHTML = jobs.length ? jobs.map(j => `<div class="job ${j.status}">
      <div class="t">${esc(j.title)}</div>
      <div class="st"><span>${esc(j.artist)}</span><span>${STATUS[j.status]} ${j.status === 'downloading' ? j.progress + '%' : ''}</span></div>
      ${['downloading', 'converting'].includes(j.status) ? `<div class="prog"><i style="width:${j.progress}%"></i></div>` : ''}
      ${j.error && j.status === 'error' ? `<div class="err">${esc(j.error)}</div>` : ''}
    </div>`).join('') : '<p class="empty">Nothing queued.</p>';
    const active = s.jobs.some(j => ['queued', 'downloading', 'converting'].includes(j.status));
    pollTimer = setTimeout(poll, active ? 700 : 3000);
  } catch {
    lcd('server stopped. relaunch ytRip', 'err');
  }
}

// ---- wiring ----
$('#search').onsubmit = e => {
  e.preventDefault();
  const q = $('#q').value.trim();
  if (!q) return;
  if (/^https?:\/\//i.test(q)) return openUrl(q);
  state.q = q; state.page = 1;
  runSearch();
};

$('#tabs').onclick = e => {
  const b = e.target.closest('button');
  if (!b) return;
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  state.tab = b.dataset.tab;
  if (state.q) { state.page = 1; runSearch(); }
};

$('#results').addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.matches('[data-open]')) e.target.click();
});

$('#clear').onclick = () => api('/api/clear', {}).then(poll);

$('#save-lib').onclick = async () => {
  try {
    const r = await api('/api/settings', { library: $('#library').value });
    $('#library').value = r.settings.library;
    lcd('library saved');
  } catch (e) { lcd(e.message, 'err'); }
};

$('#quit').onclick = async () => {
  if (!confirm('Quit ytRip? Active downloads will stop.')) return;
  await api('/api/quit', {}).catch(() => {});
  clearTimeout(pollTimer);
  lcd('ytrip stopped. you can close this tab', 'err');
};

new EventSource('/api/live');  // keeps the server alive while this tab is open
poll();
