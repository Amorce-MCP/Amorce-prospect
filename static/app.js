'use strict';

class AmorceApp {
  constructor() {
    this.prospects = [];
    this._cards = new Map();
    this._seq = 0;
    this.isRunning = false;
    this.sortDesc = true;
    this.filter = 'all';
    this._currentProspectId = null;
    this._ewQuestions = [];
    this._ewChannel = 'email';
    this._bindDOM();
    this._loadProspects();
  }

  // ── DOM wiring ──────────────────────────────────────────────────────────────

  _bindDOM() {
    this._urlInput      = document.getElementById('url-input');
    this._urlCounter    = document.getElementById('url-counter');
    this._btnStart      = document.getElementById('btn-start');
    this._btnClear      = document.getElementById('btn-clear');
    this._workflowSect  = document.getElementById('workflow-section');
    this._workflowGrid  = document.getElementById('workflow-grid');
    this._tbody         = document.getElementById('prospects-tbody');
    this._btnExport     = document.getElementById('btn-export');
    this._thScore       = document.getElementById('th-score');

    // Modal
    this._modal             = document.getElementById('prospect-modal');
    this._modalClose        = document.getElementById('modal-close');
    this._modalCompanyName  = document.getElementById('modal-company-name');
    this._modalCompanyUrl   = document.getElementById('modal-company-url');
    this._modalAnalysis     = document.getElementById('modal-analysis');

    // Chatbot toggle
    this._chatbotBtnYes     = document.getElementById('chatbot-btn-yes');
    this._chatbotBtnUnknown = document.getElementById('chatbot-btn-unknown');
    this._chatbotBtnNo      = document.getElementById('chatbot-btn-no');

    // Email workflow states
    this._ewStateInit      = document.getElementById('ew-state-init');
    this._ewStateQuestions = document.getElementById('ew-state-questions');
    this._ewStateEmail     = document.getElementById('ew-state-email');
    this._ewQuestionsList  = document.getElementById('ew-questions-list');

    // Email workflow buttons
    this._btnGenQuestions   = document.getElementById('btn-generate-questions');
    this._btnGenEmail       = document.getElementById('btn-generate-email');
    this._btnSaveEmail      = document.getElementById('btn-save-email');
    this._btnCopyEmail      = document.getElementById('btn-copy-email');
    this._btnGmail          = document.getElementById('btn-gmail');
    this._btnRestartQ       = document.getElementById('btn-restart-questions');
    this._btnPolish              = document.getElementById('btn-polish');
    this._ewSubject              = document.getElementById('ew-subject');
    this._ewBody                 = document.getElementById('ew-body');
    this._ewPolishInstruct       = document.getElementById('ew-polish-instruction');
    this._ewLangEn               = document.getElementById('ew-lang-en');

    // LinkedIn elements
    this._ewStateLinkedIn        = document.getElementById('ew-state-linkedin');
    this._ewLinkedInMsg          = document.getElementById('ew-linkedin-msg');
    this._btnCopyLinkedIn        = document.getElementById('btn-copy-linkedin');
    this._btnRestartLinkedIn     = document.getElementById('btn-restart-linkedin');
    this._ewLinkedInPolishInstruct = document.getElementById('ew-linkedin-polish-instruction');
    this._btnPolishLinkedIn      = document.getElementById('btn-polish-linkedin');

    // Channel buttons
    this._chBtnEmail             = document.getElementById('ew-ch-email');
    this._chBtnLinkedIn          = document.getElementById('ew-ch-linkedin');

    // Events
    this._urlInput.addEventListener('input', () => this._onUrlInput());
    this._btnStart.addEventListener('click', () => this._onStart());
    this._btnClear.addEventListener('click', () => this._onClear());
    this._btnExport.addEventListener('click', () => this.exportCSV());
    this._thScore.addEventListener('click', () => this._toggleSort());

    this._modalClose.addEventListener('click', () => this._closeModal());
    this._modal.addEventListener('click', e => {
      if (e.target === this._modal) this._closeModal();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') this._closeModal();
    });

    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.filter = btn.dataset.filter;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this._renderTable();
      });
    });

    this._tbody.addEventListener('click', e => {
      const btn = e.target.closest('[data-open-prospect]');
      if (btn) this._openProspect(btn.dataset.openProspect);
    });

    // Chatbot toggle
    [this._chatbotBtnYes, this._chatbotBtnUnknown, this._chatbotBtnNo].forEach(btn => {
      btn.addEventListener('click', () => this._onChatbotToggle(btn.dataset.val));
    });

    // Email workflow
    this._btnGenQuestions.addEventListener('click', () => this._onGenerateQuestions());
    this._btnGenEmail.addEventListener('click', () => this._onGenerateMessage());
    this._btnSaveEmail.addEventListener('click', () => this._onSaveEmail());
    this._btnCopyEmail.addEventListener('click', () => this._onCopyEmail());
    this._btnRestartQ.addEventListener('click', () => this._showEwState('init'));
    this._btnPolish.addEventListener('click', () => this._onPolish());

    // LinkedIn workflow
    this._btnCopyLinkedIn.addEventListener('click', () => this._onCopyLinkedIn());
    this._btnRestartLinkedIn.addEventListener('click', () => this._showEwState('init'));
    this._btnPolishLinkedIn.addEventListener('click', () => this._onPolishLinkedIn());

    // Channel selector
    [this._chBtnEmail, this._chBtnLinkedIn].forEach(btn => {
      btn.addEventListener('click', () => this._onChannelSwitch(btn.dataset.channel));
    });
  }

  // ── URL input helpers ───────────────────────────────────────────────────────

  _parseUrls() {
    return this._urlInput.value
      .split('\n')
      .map(l => l.trim())
      .filter(l => l.startsWith('http://') || l.startsWith('https://'));
  }

  _onUrlInput() {
    const n = this._parseUrls().length;
    this._urlCounter.textContent = `${n} URL${n !== 1 ? 's' : ''} détectée${n !== 1 ? 's' : ''}`;
    this._btnStart.disabled = n === 0 || this.isRunning;
  }

  _onClear() {
    this._urlInput.value = '';
    this._onUrlInput();
  }

  _onStart() {
    const urls = this._parseUrls();
    if (urls.length) this.startWorkflow(urls);
  }

  _setRunning(running) {
    this.isRunning = running;
    this._btnStart.disabled = running || this._parseUrls().length === 0;
    this._btnStart.querySelector('.btn-icon').classList.toggle('hidden', running);
    this._btnStart.querySelector('.spinner').classList.toggle('hidden', !running);
    this._btnStart.querySelector('.btn-text').textContent =
      running ? 'Traitement…' : 'Lancer la prospection';
  }

  // ── Workflow ────────────────────────────────────────────────────────────────

  async startWorkflow(urls) {
    this._setRunning(true);
    this._workflowSect.classList.remove('hidden');

    let data;
    try {
      const resp = await fetch('/api/start-workflow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls }),
      });
      if (!resp.ok) { this._setRunning(false); return; }
      data = await resp.json();
    } catch {
      this._setRunning(false);
      return;
    }

    const { workflow_id } = data;
    for (const url of urls) this._ensureCard(workflow_id, url);
    this._connectWebSocket(workflow_id, urls.length);
  }

  _connectWebSocket(workflowId, urlCount, reconnects = 0) {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/${workflowId}`);
    let doneCount = 0;

    ws.onmessage = e => {
      try {
        const event = JSON.parse(e.data);
        this.handleEvent(event);
        if (event.step === 'done' || event.step === 'error') {
          doneCount++;
          if (doneCount >= urlCount) {
            ws.close();
            this._setRunning(false);
            this._loadProspects();
          }
        }
      } catch { /* ignore parse errors */ }
    };

    ws.onerror = () => {};

    ws.onclose = () => {
      if (this.isRunning && reconnects < 3) {
        setTimeout(() => this._connectWebSocket(workflowId, urlCount, reconnects + 1), 1500);
      } else if (this.isRunning) {
        this._setRunning(false);
      }
    };
  }

  // ── Workflow cards ──────────────────────────────────────────────────────────

  _cardKey(workflowId, url) { return `${workflowId}::${url}`; }

  _ensureCard(workflowId, url) {
    const key = this._cardKey(workflowId, url);
    if (!this._cards.has(key)) this._createCard(workflowId, url, key);
    return this._cards.get(key);
  }

  _createCard(workflowId, url, key) {
    const n = ++this._seq;
    this._cards.set(key, n);

    const displayUrl = url.replace(/^https?:\/\//, '').replace(/\/$/, '');
    const card = document.createElement('div');
    card.className = 'wf-card';
    card.id = `wf-card-${n}`;
    card.innerHTML = `
      <div class="wf-card-header">
        <span class="wf-url" title="${this._esc(url)}">${this._esc(displayUrl)}</span>
        <span class="wf-score" id="wf-score-${n}"></span>
      </div>
      <div class="wf-progress-track">
        <div class="wf-progress-fill" id="wf-prog-${n}"></div>
      </div>
      <div class="wf-pipeline">
        <div class="wf-step waiting" id="wf-step-${n}-0">
          <div class="step-dot">🔍</div><span class="step-label">Scraping</span>
        </div>
        <div class="wf-step waiting" id="wf-step-${n}-1">
          <div class="step-dot">🔬</div><span class="step-label">Analyse</span>
        </div>
        <div class="wf-step waiting" id="wf-step-${n}-2">
          <div class="step-dot">🧠</div><span class="step-label">Qualif.</span>
        </div>
        <div class="wf-step waiting" id="wf-step-${n}-3">
          <div class="step-dot">✓</div><span class="step-label">Terminé</span>
        </div>
      </div>
      <div class="wf-meta">
        <span class="badge hidden" id="wf-badge-${n}"></span>
      </div>
      <div class="wf-analysis-panel hidden" id="wf-ap-${n}"></div>
      <p class="wf-error-msg hidden" id="wf-err-${n}"></p>
    `;
    this._workflowGrid.prepend(card);
    return n;
  }

  handleEvent(event) {
    const { workflow_id, url, step, message, progress, data } = event;
    const key = this._cardKey(workflow_id, url);
    const n   = this._cards.get(key);
    if (!n) return;

    const card = document.getElementById(`wf-card-${n}`);
    const prog = document.getElementById(`wf-prog-${n}`);
    if (prog) prog.style.width = `${progress}%`;

    const STEP_IDX   = { scraping: 0, analyzing: 1, qualifying: 2, done: 3 };
    const STEP_COUNT = 4;

    if (step === 'error') {
      card.classList.add('state-error');
      const errEl = document.getElementById(`wf-err-${n}`);
      if (errEl) { errEl.textContent = message; errEl.classList.remove('hidden'); }
      for (let i = 0; i < STEP_COUNT; i++) {
        const s = document.getElementById(`wf-step-${n}-${i}`);
        if (s && s.classList.contains('active')) { s.classList.remove('active'); s.classList.add('error'); }
      }
      return;
    }

    const idx = STEP_IDX[step] ?? -1;
    for (let i = 0; i < STEP_COUNT; i++) {
      const s = document.getElementById(`wf-step-${n}-${i}`);
      if (!s) continue;
      s.classList.remove('waiting', 'active', 'done', 'error');
      if (i < idx) s.classList.add('done');
      else if (i === idx) s.classList.add('active');
      else s.classList.add('waiting');
    }

    if (step === 'done' && data) {
      card.classList.add('state-done');
      for (let i = 0; i < STEP_COUNT; i++) {
        const s = document.getElementById(`wf-step-${n}-${i}`);
        if (s) { s.classList.remove('waiting', 'active'); s.classList.add('done'); }
      }
      const scoreEl = document.getElementById(`wf-score-${n}`);
      if (scoreEl) scoreEl.textContent = '⭐'.repeat(data.score || 0);

      const badgeEl = document.getElementById(`wf-badge-${n}`);
      if (badgeEl && data.suggested_mission) {
        badgeEl.textContent = data.suggested_mission;
        badgeEl.className   = `badge ${this._missionBadgeClass(data.suggested_mission)}`;
        badgeEl.classList.remove('hidden');
      }

      if (data.analysis) {
        const apEl = document.getElementById(`wf-ap-${n}`);
        if (apEl) {
          apEl.innerHTML = this._renderAnalysisPanel(data.analysis);
          apEl.classList.remove('hidden');
        }
      }
    }
  }

  // ── Analysis panel ──────────────────────────────────────────────────────────

  _renderGeoBreakdown(a) {
    const geo = a.geo_score || 0;
    const geoColor = geo <= 35 ? '#e74c3c' : (geo <= 65 ? '#f39c12' : '#1abc9c');
    const bd = a.geo_breakdown || {};
    const signals = [
      { key: 'schema_org',      label: 'Schema.org',      max: 20 },
      { key: 'faq_content',     label: 'FAQ / Q&A',       max: 20 },
      { key: 'named_entities',  label: 'Entités nommées', max: 15 },
      { key: 'factual_content', label: 'Contenu factuel', max: 15 },
      { key: 'freshness',       label: 'Fraîcheur',       max: 15 },
      { key: 'multichannel',    label: 'Multi-canaux',    max: 15 },
    ];
    const rows = signals.map(s => {
      const val = bd[s.key] ?? 0;
      const pct = s.max > 0 ? Math.round((val / s.max) * 100) : 0;
      const c = pct >= 80 ? '#1abc9c' : (pct >= 40 ? '#f39c12' : '#e74c3c');
      const check = pct >= 80 ? ' ✅' : '';
      return `<div class="ap-geo-bd-row">
        <span class="ap-geo-bd-label">${s.label}</span>
        <div class="ap-geo-bd-bar-wrap">
          <div class="ap-geo-bd-track"><div class="ap-geo-bd-bar" style="width:${pct}%;background:${c}"></div></div>
          <span class="ap-geo-bd-val" style="color:${c}">${val}/${s.max}${check}</span>
        </div>
      </div>`;
    }).join('');
    const priority = signals.reduce((w, s) => {
      const gap = s.max - (bd[s.key] ?? 0);
      return gap > w.gap ? { label: s.label, gap } : w;
    }, { label: '', gap: -1 });
    const hint = priority.label
      ? `<div class="ap-geo-priority">Action prioritaire : améliorer <b>${priority.label}</b></div>`
      : '';
    return `<div class="ap-geo-section">
      <div class="ap-geo-header">
        <span class="ap-label">Score GEO</span>
        <span class="ap-geo-val" style="color:${geoColor}">${geo}/100</span>
      </div>
      ${rows}
      ${hint}
    </div>`;
  }

  _renderAnalysisPanel(a) {
    const readColor = a.ai_readiness === 'faible' ? '#e74c3c'
                    : a.ai_readiness === 'moyen'  ? '#f39c12' : '#1abc9c';
    const recs = (a.recommendations || []).slice(0, 3)
      .map((r, i) => `<div class="ap-rec">${i + 1}. ${this._esc(r)}</div>`)
      .join('');
    return `<div class="wf-analysis-inner">
      <div class="ap-title">Analyse du site</div>
      ${this._renderGeoBreakdown(a)}
      <div class="ap-row">
        <span class="ap-label">Readiness IA</span>
        <span class="ap-val" style="color:${readColor}">${this._esc(a.ai_readiness || '—')}</span>
      </div>
      <div class="ap-divider"></div>
      <div class="ap-gap"><b>Manque :</b> ${this._esc(a.main_gap || '—')}</div>
      <div class="ap-gap"><b>Action rapide :</b> ${this._esc(a.quick_win || '—')}</div>
      ${recs ? `<div class="ap-divider"></div><div class="ap-recs-title">Recommandations</div>${recs}` : ''}
    </div>`;
  }

  _missionBadgeClass(mission) {
    if (!mission) return 'badge-default';
    const m = mission.toLowerCase();
    if (m.includes('mcp'))  return 'badge-mcp';
    if (m.includes('rag') || m.includes('chatbot')) return 'badge-rag';
    if (m.includes('geo'))  return 'badge-geo';
    if (m.includes('n8n'))  return 'badge-n8n';
    return 'badge-default';
  }

  // ── Prospects table ─────────────────────────────────────────────────────────

  async _loadProspects() {
    try {
      const resp = await fetch('/api/prospects');
      if (!resp.ok) return;
      this.prospects = await resp.json();
      this._renderTable();
    } catch { /* ignore */ }
  }

  _renderTable() {
    let data = [...this.prospects];

    if (this.filter !== 'all') {
      const score = parseInt(this.filter, 10);
      data = data.filter(p => p.score === score);
    }

    data.sort((a, b) => this.sortDesc ? b.score - a.score : a.score - b.score);

    if (!data.length) {
      this._tbody.innerHTML =
        '<tr class="empty-row"><td colspan="7">Aucun prospect. Lancez une prospection !</td></tr>';
      return;
    }

    this._tbody.innerHTML = data.map(p => this._prospectRow(p)).join('');

    const arrow = this._thScore.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = this.sortDesc ? '↓' : '↑';
  }

  _chatbotLabel(hasBot) {
    if (hasBot === true)  return '<span class="chatbot-pill chatbot-yes">Oui</span>';
    if (hasBot === false) return '<span class="chatbot-pill chatbot-no">Non</span>';
    return '<span class="chatbot-pill chatbot-unknown">?</span>';
  }

  _prospectRow(p) {
    const stars       = '⭐'.repeat(p.score || 0);
    const statusClass = `status-${p.status || 'pending'}`;
    const STATUS_LABEL = {
      email_written: 'Email rédigé',
      qualified:     'Qualifié',
      pending:       'En attente',
      error:         'Erreur',
    };
    const statusLabel  = STATUS_LABEL[p.status] || (p.status || 'En attente');
    const missionHtml  = p.suggested_mission
      ? `<span class="badge ${this._missionBadgeClass(p.suggested_mission)}">${this._esc(p.suggested_mission)}</span>`
      : '—';
    const displayUrl   = (p.url || '').replace(/^https?:\/\//, '').replace(/\/$/, '');

    return `
      <tr>
        <td>
          <div class="company-name">${this._esc(p.company_name || '—')}</div>
          <div class="company-url">${this._esc(displayUrl)}</div>
        </td>
        <td><span class="score-stars">${stars}</span></td>
        <td><span class="need-text" title="${this._esc(p.detected_need || '')}">${this._esc(p.detected_need || '—')}</span></td>
        <td>${missionHtml}</td>
        <td>${this._chatbotLabel(p.has_chatbot)}</td>
        <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
        <td>
          <button class="btn btn-ghost btn-sm" data-open-prospect="${this._esc(p.id)}">Ouvrir</button>
        </td>
      </tr>`;
  }

  _toggleSort() {
    this.sortDesc = !this.sortDesc;
    this._thScore.classList.toggle('sort-desc',  this.sortDesc);
    this._thScore.classList.toggle('sort-asc',  !this.sortDesc);
    this._renderTable();
  }

  // ── Prospect modal ──────────────────────────────────────────────────────────

  _openProspect(prospectId) {
    const p = this.prospects.find(x => x.id === prospectId);
    if (!p) return;

    this._currentProspectId = prospectId;
    this._ewQuestions = [];
    this._ewChannel = 'email';
    this._chBtnEmail.classList.add('ew-channel-active');
    this._chBtnLinkedIn.classList.remove('ew-channel-active');
    this._btnGenEmail.querySelector('.btn-icon').textContent = '✉️';
    this._btnGenEmail.querySelector('.btn-text').textContent = "Générer l'email";

    this._modalCompanyName.textContent = p.company_name || '—';
    this._modalCompanyUrl.textContent  = (p.url || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
    this._modalCompanyUrl.href         = p.url || '#';

    this._setChatbotToggle(p.has_chatbot);

    if (p.analysis) {
      this._modalAnalysis.innerHTML = this._renderAnalysisPanel(p.analysis);
    } else {
      this._modalAnalysis.innerHTML = '';
    }

    if (p.email_subject) {
      this._ewSubject.value = p.email_subject;
      this._ewBody.value    = p.email_body || '';
      this._updateGmailLink(p.email_subject, p.email_body || '');
      this._showEwState('email');
    } else {
      this._showEwState('init');
    }

    this._modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  _closeModal() {
    this._modal.classList.add('hidden');
    document.body.style.overflow = '';
    this._currentProspectId = null;
  }

  // ── Chatbot toggle ──────────────────────────────────────────────────────────

  _setChatbotToggle(hasBot) {
    const YES = 'chatbot-btn-active-yes';
    const NO  = 'chatbot-btn-active-no';
    const UNK = 'chatbot-btn-active-none';
    this._chatbotBtnYes.className     = `chatbot-btn${hasBot === true  ? ' ' + YES : ''}`;
    this._chatbotBtnNo.className      = `chatbot-btn${hasBot === false ? ' ' + NO  : ''}`;
    this._chatbotBtnUnknown.className = `chatbot-btn${hasBot === null || hasBot === undefined ? ' ' + UNK : ''}`;
  }

  async _onChatbotToggle(val) {
    if (!this._currentProspectId) return;
    const parsed = val === 'true' ? true : val === 'false' ? false : null;
    this._setChatbotToggle(parsed);

    try {
      await fetch(`/api/prospects/${this._currentProspectId}/chatbot`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ has_chatbot: parsed }),
      });
      const p = this.prospects.find(x => x.id === this._currentProspectId);
      if (p) p.has_chatbot = parsed;
      this._renderTable();
    } catch { /* ignore */ }
  }

  // ── Email workflow states ───────────────────────────────────────────────────

  _showEwState(state) {
    this._ewStateInit.classList.toggle('hidden',      state !== 'init');
    this._ewStateQuestions.classList.toggle('hidden', state !== 'questions');
    this._ewStateEmail.classList.toggle('hidden',     state !== 'email');
    this._ewStateLinkedIn.classList.toggle('hidden',  state !== 'linkedin');
  }

  _onChannelSwitch(channel) {
    this._ewChannel = channel;
    this._chBtnEmail.classList.toggle('ew-channel-active',    channel === 'email');
    this._chBtnLinkedIn.classList.toggle('ew-channel-active', channel === 'linkedin');
    const genBtn = this._btnGenEmail;
    if (channel === 'linkedin') {
      genBtn.querySelector('.btn-icon').textContent = '💼';
      genBtn.querySelector('.btn-text').textContent = 'Générer le message LinkedIn';
    } else {
      genBtn.querySelector('.btn-icon').textContent = '✉️';
      genBtn.querySelector('.btn-text').textContent = "Générer l'email";
    }
    this._showEwState('init');
  }

  _setBtnLoading(btn, loading) {
    btn.disabled = loading;
    btn.querySelector('.spinner')?.classList.toggle('hidden', !loading);
    btn.querySelector('.btn-text')?.classList.toggle('hidden', loading);
    btn.querySelector('.btn-icon')?.classList.toggle('hidden', loading);
  }

  async _onGenerateQuestions() {
    if (!this._currentProspectId) return;
    this._setBtnLoading(this._btnGenQuestions, true);
    try {
      const resp = await fetch(`/api/prospects/${this._currentProspectId}/email/questions`, {
        method: 'POST',
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      this._ewQuestions = data.questions || [];
      this._renderQuestions();
      this._showEwState('questions');
    } catch (err) {
      console.error('Failed to generate questions:', err);
    } finally {
      this._setBtnLoading(this._btnGenQuestions, false);
    }
  }

  _renderQuestions() {
    this._ewQuestionsList.innerHTML = this._ewQuestions.map((q, i) => `
      <div class="ew-question-block">
        <label class="ew-question-label">${this._esc(q)}</label>
        <textarea class="ew-answer-textarea" id="ew-answer-${i}" rows="2"
          placeholder="Votre réponse..."></textarea>
      </div>
    `).join('');
  }

  async _onGenerateMessage() {
    if (this._ewChannel === 'linkedin') {
      await this._onGenerateLinkedIn();
    } else {
      await this._onGenerateEmail();
    }
  }

  async _onGenerateEmail() {
    if (!this._currentProspectId) return;
    const answers = this._ewQuestions.map((_, i) => {
      const el = document.getElementById(`ew-answer-${i}`);
      return el ? el.value.trim() : '';
    });

    this._setBtnLoading(this._btnGenEmail, true);
    try {
      const language = this._ewLangEn.checked ? 'en' : 'fr';
      const resp = await fetch(`/api/prospects/${this._currentProspectId}/email/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ questions: this._ewQuestions, answers, language }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      this._ewSubject.value = data.subject || '';
      this._ewBody.value    = data.body || '';
      this._updateGmailLink(data.subject || '', data.body || '');

      const p = this.prospects.find(x => x.id === this._currentProspectId);
      if (p) { p.email_subject = data.subject; p.email_body = data.body; p.status = 'email_written'; }
      this._renderTable();
      this._showEwState('email');
    } catch (err) {
      console.error('Failed to generate email:', err);
    } finally {
      this._setBtnLoading(this._btnGenEmail, false);
    }
  }

  async _onGenerateLinkedIn() {
    if (!this._currentProspectId) return;
    const answers = this._ewQuestions.map((_, i) => {
      const el = document.getElementById(`ew-answer-${i}`);
      return el ? el.value.trim() : '';
    });

    this._setBtnLoading(this._btnGenEmail, true);
    try {
      const language = this._ewLangEn.checked ? 'en' : 'fr';
      const resp = await fetch(`/api/prospects/${this._currentProspectId}/linkedin/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ questions: this._ewQuestions, answers, language }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      this._ewLinkedInMsg.value = data.message || '';
      this._showEwState('linkedin');
    } catch (err) {
      console.error('Failed to generate LinkedIn message:', err);
    } finally {
      this._setBtnLoading(this._btnGenEmail, false);
    }
  }

  _onCopyLinkedIn() {
    navigator.clipboard.writeText(this._ewLinkedInMsg.value).catch(() => {});
  }

  async _onPolishLinkedIn() {
    if (!this._currentProspectId) return;
    const message     = this._ewLinkedInMsg.value;
    const instruction = this._ewLinkedInPolishInstruct.value.trim();

    this._setBtnLoading(this._btnPolishLinkedIn, true);
    try {
      const language = this._ewLangEn.checked ? 'en' : 'fr';
      const resp = await fetch(`/api/prospects/${this._currentProspectId}/linkedin/polish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, instruction, language }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      this._ewLinkedInMsg.value = data.message || message;
      this._ewLinkedInPolishInstruct.value = '';
    } catch (err) {
      console.error('LinkedIn polish failed:', err);
    } finally {
      this._setBtnLoading(this._btnPolishLinkedIn, false);
    }
  }

  async _onSaveEmail() {
    if (!this._currentProspectId) return;
    const subject = this._ewSubject.value;
    const body    = this._ewBody.value;
    try {
      await fetch(`/api/prospects/${this._currentProspectId}/email`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject, body }),
      });
      const p = this.prospects.find(x => x.id === this._currentProspectId);
      if (p) { p.email_subject = subject; p.email_body = body; p.status = 'email_written'; }
      this._renderTable();
      this._updateGmailLink(subject, body);
    } catch { /* ignore */ }
  }

  _onCopyEmail() {
    const text = `Objet : ${this._ewSubject.value}\n\n${this._ewBody.value}`;
    navigator.clipboard.writeText(text).catch(() => {});
  }

  async _onPolish() {
    if (!this._currentProspectId) return;
    const subject     = this._ewSubject.value;
    const body        = this._ewBody.value;
    const instruction = this._ewPolishInstruct.value.trim();

    this._setBtnLoading(this._btnPolish, true);
    try {
      const language = this._ewLangEn.checked ? 'en' : 'fr';
      const resp = await fetch(`/api/prospects/${this._currentProspectId}/email/polish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject, body, instruction, language }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      this._ewSubject.value = data.subject || subject;
      this._ewBody.value    = data.body    || body;
      this._ewPolishInstruct.value = '';
      this._updateGmailLink(this._ewSubject.value, this._ewBody.value);
      const p = this.prospects.find(x => x.id === this._currentProspectId);
      if (p) { p.email_subject = this._ewSubject.value; p.email_body = this._ewBody.value; }
    } catch (err) {
      console.error('Polish failed:', err);
    } finally {
      this._setBtnLoading(this._btnPolish, false);
    }
  }

  _updateGmailLink(subject, body) {
    const su = encodeURIComponent(subject);
    const bd = encodeURIComponent(body);
    this._btnGmail.href = `https://mail.google.com/mail/?view=cm&fs=1&su=${su}&body=${bd}`;
  }

  // ── CSV export ──────────────────────────────────────────────────────────────

  exportCSV() {
    if (!this.prospects.length) return;
    const headers = ['Entreprise', 'URL', 'Score', 'Besoin détecté', 'Mission', 'Chatbot', 'Statut', 'Objet email'];
    const rows = this.prospects.map(p => [
      p.company_name      || '',
      p.url               || '',
      p.score             ?? '',
      p.detected_need     || '',
      p.suggested_mission || '',
      p.has_chatbot === true ? 'Oui' : p.has_chatbot === false ? 'Non' : '?',
      p.status            || '',
      p.email_subject     || '',
    ]);
    const csv = [headers, ...rows]
      .map(row => row.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `amorce-prospects-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Utils ───────────────────────────────────────────────────────────────────

  _esc(str) {
    return String(str ?? '')
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;');
  }
}

const app = new AmorceApp();
