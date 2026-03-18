/* ── State ────────────────────────────────────────────── */
let pdfFiles = [];
let xlFiles  = [];
let _lastParsedFile = null;

/* ── Drag / drop ─────────────────────────────────────── */
function dzOver(e, id) {
  e.preventDefault();
  document.getElementById(id).classList.add('dragover');
}
function dzLeave(id) {
  document.getElementById(id).classList.remove('dragover');
}
function dzDrop(e, type) {
  e.preventDefault();
  const id = type === 'pdf' ? 'dz-pdf' : 'dz-xl';
  document.getElementById(id).classList.remove('dragover');
  addFiles(Array.from(e.dataTransfer.files), type);
}
function onInput(input, type) {
  addFiles(Array.from(input.files), type);
  input.value = '';
}

/* ── File management ─────────────────────────────────── */
function ext(name) { return name.split('.').pop().toLowerCase(); }

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function addFiles(files, type) {
  if (type === 'pdf') {
    files
      .filter(f => ext(f.name) === 'pdf')
      .forEach(f => { if (!pdfFiles.find(x => x.name === f.name)) pdfFiles.push(f); });
  } else {
    files
      .filter(f => ['xlsx','xls','xlsm'].includes(ext(f.name)))
      .forEach(f => {
        if (xlFiles.length < 2 && !xlFiles.find(x => x.name === f.name)) xlFiles.push(f);
      });
  }
  renderLists();
  updateMode();
}

function removeFile(type, name) {
  if (type === 'pdf') pdfFiles = pdfFiles.filter(f => f.name !== name);
  else               xlFiles  = xlFiles.filter(f => f.name !== name);
  // Сбрасываем кнопку если файлы изменились
  hideNextBtn();
  document.getElementById('result-inline').innerHTML = '';
  renderLists();
  updateMode();
}

function renderLists() {
  renderList('list-pdf', pdfFiles, 'pdf');
  renderList('list-xl',  xlFiles,  'xl');
}

function renderList(id, arr, type) {
  const el = document.getElementById(id);
  if (!arr.length) { el.innerHTML = ''; return; }
  el.innerHTML = arr.map(f => `
    <li class="file-chip">
      <div class="chip-icon chip-${type}">${type === 'pdf' ? 'PDF' : 'XLS'}</div>
      <span class="chip-name" title="${esc(f.name)}">${esc(f.name)}</span>
      <span class="chip-size">${fmtSize(f.size)}</span>
      <button class="chip-rm" onclick="removeFile('${type}','${esc(f.name)}')" title="Убрать">×</button>
    </li>`).join('');
}

function esc(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ── Mode detection ──────────────────────────────────── */
const MODES = {
  NONE:        { title: 'Загрузите хотя бы один PDF',    sub: 'Режим обработки определится автоматически',                   ready: false, warn: false },
  PDF_ONLY:    { title: 'Режим: один PDF',                sub: 'Будет вызвана функция parse_pdf_all',                         ready: true,  warn: false },
  PDF_EXCEL:   { title: 'Режим: PDF + два Excel',         sub: 'Будут вызваны parse_excel и parse_pdf_thicknessonly',         ready: true,  warn: false },
  MULTI_PDF:   { title: 'Режим: несколько PDF',           sub: 'Откроется постраничный просмотр, parse_pdf_all для каждого',  ready: true,  warn: false },
  NEED_XL2:    { title: 'Нужен второй Excel-файл',        sub: 'Добавьте второй .xlsx или уберите первый',                   ready: false, warn: true  },
  TOO_MANY_XL: { title: 'Слишком много Excel-файлов',     sub: 'При наличии PDF — максимум два Excel-файла',                 ready: false, warn: true  },
};

function detectMode() {
  const p = pdfFiles.length, x = xlFiles.length;
  if (p === 0)            return 'NONE';
  if (p === 1 && x === 0) return 'PDF_ONLY';
  if (p === 1 && x === 2) return 'PDF_EXCEL';
  if (p === 1 && x === 1) return 'NEED_XL2';
  if (p === 1 && x > 2)   return 'TOO_MANY_XL';
  if (p > 1  && x === 0)  return 'MULTI_PDF';
  if (p > 1  && x > 0)    return 'TOO_MANY_XL';
  return 'NONE';
}

const checkIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
const infoIcon  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
const warnIcon  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

function updateMode() {
  const key    = detectMode();
  const m      = MODES[key];
  const banner = document.getElementById('mode-banner');
  const icon   = document.getElementById('mode-icon');
  document.getElementById('mode-title').textContent = m.title;
  document.getElementById('mode-sub').textContent   = m.sub;
  document.getElementById('btn-run').disabled       = !m.ready;
  banner.classList.toggle('ready', m.ready);
  banner.classList.toggle('warn',  m.warn);
  icon.innerHTML = m.ready ? checkIcon : (m.warn ? warnIcon : infoIcon);
}

/* ── "Идти дальше" ───────────────────────────────────── */
function showNextBtn(fileName) {
  _lastParsedFile = fileName || null;
  const btn = document.getElementById('btn-next');
  if (!btn) return;
  // Сбрасываем display чтобы анимация сработала заново
  btn.style.display = 'none';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    btn.style.display = 'flex';
  }));
}

function hideNextBtn() {
  _lastParsedFile = null;
  const btn = document.getElementById('btn-next');
  if (btn) btn.style.display = 'none';
}

function goNext() {
  const param = _lastParsedFile
    ? `?file=${encodeURIComponent(_lastParsedFile)}`
    : '';
  window.location.href = `/frontend/raschet.html${param}`;
}

/* ── Navigation ──────────────────────────────────────── */
function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo(0, 0);
}

function goBack() {
  hideNextBtn();
  document.getElementById('result-inline').innerHTML = '';
  showPage('page-upload');
}

/* ── Run ─────────────────────────────────────────────── */
async function run() {
  const mode = detectMode();
  hideNextBtn();

  if (mode === 'MULTI_PDF') {
    buildMultiPage();
    return;
  }

  if (mode === 'PDF_ONLY') {
    // Остаёмся на page-upload, результат рендерим инлайн под баннером
    const inline = document.getElementById('result-inline');
    inline.innerHTML = `<div class="loading-state"><span class="spinner"></span> Обрабатываем файл…</div>`;

    const fd = new FormData();
    fd.append('pdf', pdfFiles[0]);

    try {
      const r = await fetch('/upload/pdf-only', { method: 'POST', body: fd });
      if (!r.ok) throw await r.text();
      const data = await r.json();
      inline.innerHTML = renderSingleResult(data);

      if (data.status === 'ok') {
        showNextBtn(data.file);
      }
    } catch (err) {
      inline.innerHTML = `<div class="result-card">
        <div class="result-status err">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          Ошибка: ${esc(String(err))}
        </div>
      </div>`;
    }
    return;
  }

  if (mode === 'PDF_EXCEL') {
    showPage('page-result');
    const body = document.getElementById('result-body');
    body.innerHTML = `<div class="loading-state"><span class="spinner"></span> Обрабатываем файлы…</div>`;

    try {
      const fd = new FormData();
      fd.append('pdf',    pdfFiles[0]);
      fd.append('excel1', xlFiles[0]);
      fd.append('excel2', xlFiles[1]);
      const r = await fetch('/upload/pdf-excel', { method: 'POST', body: fd });
      if (!r.ok) throw await r.text();
      const data = await r.json();
      body.innerHTML = data.results.map(renderSingleResult).join('');
    } catch (err) {
      body.innerHTML = `<div class="result-card">
        <div class="result-status err">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          Ошибка: ${esc(String(err))}
        </div>
      </div>`;
    }
  }
}

/* ── Render result card ──────────────────────────────── */
function renderSingleResult(d) {
  const files     = d.files ? d.files : (d.file ? [d.file] : []);
  const isOk      = d.status === 'ok';
  const statusSvg = isOk
    ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`
    : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
  const rawId = 'raw-' + Math.random().toString(36).slice(2);
  return `
    <div class="result-card">
      <div class="result-fn">${esc(d.function || '—')}</div>
      <div class="result-msg">${esc(d.message || '')}</div>
      <div class="result-files">${files.map(f => `<span class="result-file">${esc(f)}</span>`).join('')}</div>
      <div class="result-status ${isOk ? 'ok' : 'err'}">${statusSvg} ${isOk ? 'Успешно' : 'Ошибка'}</div>
      <button class="raw-toggle" onclick="toggleRaw('${rawId}')">Показать JSON</button>
      <pre class="raw-json" id="${rawId}">${esc(JSON.stringify(d, null, 2))}</pre>
    </div>`;
}

function toggleRaw(id) {
  const el  = document.getElementById(id);
  const btn = el.previousElementSibling;
  if (el.style.display === 'block') {
    el.style.display = 'none';
    btn.textContent  = 'Показать JSON';
  } else {
    el.style.display = 'block';
    btn.textContent  = 'Скрыть JSON';
  }
}

/* ── Multi-PDF page ──────────────────────────────────── */
function buildMultiPage() {
  showPage('page-multi');
  const tabsBar  = document.getElementById('tabs-bar');
  const tabsCont = document.getElementById('tabs-content');
  tabsBar.innerHTML  = '';
  tabsCont.innerHTML = '';

  pdfFiles.forEach((file, i) => {
    const btn = document.createElement('button');
    btn.className   = 'tab-btn' + (i === 0 ? ' active' : '');
    btn.textContent = file.name.length > 22 ? file.name.slice(0, 20) + '…' : file.name;
    btn.title       = file.name;
    btn.onclick     = () => activateTab(i);
    tabsBar.appendChild(btn);

    const pane = document.createElement('div');
    pane.className = 'tab-pane' + (i === 0 ? ' active' : '');
    pane.id        = `pane-${i}`;
    pane.innerHTML = `
      <div class="file-panel-head">
        <div>
          <div class="file-panel-name">${esc(file.name)}</div>
          <div class="file-panel-meta">${fmtSize(file.size)} · PDF</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <button class="btn-primary" id="runbtn-${i}" onclick="runSinglePdf(${i})">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            parse_pdf_all
          </button>
          <button class="btn-next" id="multi-next-${i}" style="display:none"
                  onclick="goNextFromFile('${esc(file.name)}')">
            Идти дальше
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </button>
        </div>
      </div>
      <div id="result-${i}"><p class="result-placeholder">Нажмите кнопку для запуска обработки.</p></div>`;
    tabsCont.appendChild(pane);
  });
}

function activateTab(i) {
  document.querySelectorAll('.tab-btn').forEach((b, j) => b.classList.toggle('active', j === i));
  document.querySelectorAll('.tab-pane').forEach((p, j) => p.classList.toggle('active', j === i));
}

async function runSinglePdf(i) {
  const file     = pdfFiles[i];
  const resultEl = document.getElementById(`result-${i}`);
  const btnEl    = document.getElementById(`runbtn-${i}`);
  const nextBtn  = document.getElementById(`multi-next-${i}`);

  btnEl.disabled         = true;
  nextBtn.style.display  = 'none';
  resultEl.innerHTML     = `<div class="loading-state"><span class="spinner"></span> Обрабатываем ${esc(file.name)}…</div>`;

  try {
    const fd = new FormData();
    fd.append('pdfs', file);
    const r = await fetch('/upload/multi-pdf', { method: 'POST', body: fd });
    if (!r.ok) throw await r.text();
    const data = await r.json();
    resultEl.innerHTML = data.results.map(renderSingleResult).join('');

    if (data.results.every(res => res.status === 'ok')) {
      nextBtn.style.display = 'none';
      requestAnimationFrame(() => requestAnimationFrame(() => {
        nextBtn.style.display = 'flex';
      }));
    }
  } catch (err) {
    resultEl.innerHTML = `<div class="result-card">
      <div class="result-status err">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        Ошибка: ${esc(String(err))}
      </div>
    </div>`;
  } finally {
    btnEl.disabled = false;
  }
}

function goNextFromFile(fileName) {
  window.location.href = `/frontend/raschet.html?file=${encodeURIComponent(fileName)}`;
}

/* ── Init ────────────────────────────────────────────── */
updateMode();