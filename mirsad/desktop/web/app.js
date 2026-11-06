/* Mirsad Studio — desktop interface.
 *
 * The page talks to the Python runtime through a single QWebChannel object
 * named "bridge".  When the channel is not present (for example when the
 * file is opened in a browser), the interface switches to a self-contained
 * preview with realistic sample data.  Preview data never touches disk.
 */
'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const App = {
  bridge: null,
  connected: false,
  demo: false,
  state: null,
  session: null,
  sessions: [],
  running: false,
  route: 'home',
  plan: [],
  step: 0,
  totalSteps: 0,
  planCurrent: -1,
  tools: new Map(),
  activity: [],
  audit: [],
  auditCheck: null,
  approvals: [],
  activeApproval: null,
  settingsDirty: false,
  paletteIndex: 0,
  paletteCommands: [],
  booted: false,
  lastStatus: 'Ready',
  demoListeners: [],
  renderedSessionId: null,
};

const ICONS = {
  check: 'i-check',
  alert: 'i-alert',
  x: 'i-x',
  shield: 'i-shield',
  terminal: 'i-terminal',
  file: 'i-file',
  search: 'i-search',
  arrow: 'i-arrow',
  clock: 'i-clock',
  key: 'i-key',
  folder: 'i-folder',
  plus: 'i-plus',
};

/* ── utilities ─────────────────────────────────────────────────────────── */

function icon(name, className = '') {
  const span = document.createElement('span');
  span.className = className;
  span.innerHTML = `<svg aria-hidden="true"><use href="#${name}"/></svg>`;
  return span;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function text(value) {
  return document.createTextNode(value == null ? '' : String(value));
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content != null) node.textContent = String(content);
  return node;
}

function basename(path) {
  const normalized = String(path || '').replace(/[\\/]+$/, '');
  const parts = normalized.split(/[\\/]/);
  return parts[parts.length - 1] || normalized;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function parseJson(value) {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function timeAgo(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 45) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.round(seconds / 86400)}d ago`;
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function clockTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return String(iso);
  return date.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function shortDate(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return String(iso);
  return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function padSequence(value) {
  return String(value ?? 0).padStart(3, '0');
}

function riskLabel(level) {
  return String(level || 'low').toUpperCase();
}

function showById(id, visible) {
  const node = $(id);
  if (node) node.hidden = !visible;
}

function focusSoon(selector) {
  window.setTimeout(() => {
    const node = $(selector);
    if (node) {
      node.focus();
      if (typeof node.setSelectionRange === 'function' && node.value) {
        node.setSelectionRange(node.value.length, node.value.length);
      }
    }
  }, 40);
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/* ── boot ──────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  bindStaticEvents();
  buildDemoShell();
  const initial = new URLSearchParams(window.location.search).get('view');
  if (initial && ['home', 'chat', 'activity', 'settings'].includes(initial)) {
    setRoute(initial, true);
  }
  const forceDemo = new URLSearchParams(window.location.search).get('demo') === '1';
  if (!forceDemo && hasWebChannel()) {
    connectWebChannel();
  } else {
    window.setTimeout(enterDemo, forceDemo ? 0 : 700);
  }
});

function hasWebChannel() {
  return (
    typeof QWebChannel !== 'undefined' &&
    typeof qt !== 'undefined' &&
    qt &&
    qt.webChannelTransport
  );
}

function connectWebChannel() {
  try {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      App.bridge = channel.objects.bridge;
      App.connected = true;
      if (!App.bridge) {
        enterDemo();
        return;
      }
      App.bridge.event.connect(onBridgeEvent);
      invoke('bootstrap')
        .then((response) => {
          if (response && response.ok) {
            applyState(response.state);
            finishBoot();
          } else {
            bootFailure((response && response.error) || 'The local runtime did not initialize.');
          }
        })
        .catch((error) => bootFailure(error.message || String(error)));
    });
  } catch (error) {
    bootFailure(error.message || String(error));
  }
}

function finishBoot() {
  if (App.booted) return;
  App.booted = true;
  window.setTimeout(() => {
    document.body.classList.remove('is-booting');
    const boot = $('#boot');
    if (boot) boot.setAttribute('aria-hidden', 'true');
    applyInitialScroll();
  }, 260);
}

function applyInitialScroll() {
  const anchor = new URLSearchParams(window.location.search).get('scroll');
  if (!anchor) return;
  const transcript = $('#transcript');
  if (!transcript) return;
  window.setTimeout(() => {
    if (anchor === 'top') transcript.scrollTop = 0;
    else if (anchor === 'mid') transcript.scrollTop = transcript.scrollHeight * 0.42;
    else if (anchor === 'bottom') transcript.scrollTop = transcript.scrollHeight;
    else if (/^\d+$/.test(anchor)) transcript.scrollTop = Number(anchor);
  }, 420);
}

function bootFailure(message) {
  const boot = $('#boot');
  if (boot) {
    const line = $('.boot-line', boot);
    if (line) line.remove();
    const note = el('p', 'boot-error', 'The Studio runtime could not start.');
    const detail = el('p', 'boot-error-detail', message);
    boot.appendChild(note);
    boot.appendChild(detail);
    const retry = el('button', 'btn btn-quiet boot-retry', 'Try again');
    retry.addEventListener('click', () => window.location.reload());
    boot.appendChild(retry);
  }
  document.body.classList.add('is-booting');
}

/* ── bridge calls ──────────────────────────────────────────────────────── */

function invoke(name, ...args) {
  if (App.demo) return demoInvoke(name, ...args);
  return new Promise((resolve, reject) => {
    if (!App.bridge) {
      reject(new Error('The desktop bridge is not connected.'));
      return;
    }
    let settled = false;
    const callback = (value) => {
      if (settled) return;
      settled = true;
      resolve(parseJson(value));
    };
    try {
      App.bridge[name](...args, callback);
    } catch (error) {
      reject(error);
    }
    window.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error(`The runtime did not answer ${name} in time.`));
    }, 30000);
  });
}

function notify(name, ...args) {
  if (App.demo) {
    demoNotify(name, ...args);
    return;
  }
  if (!App.bridge) return;
  try {
    App.bridge[name](...args);
  } catch (error) {
    console.error(`Bridge call ${name} failed`, error);
  }
}

function onBridgeEvent(name, raw) {
  let payload = {};
  try {
    payload = JSON.parse(raw || '{}');
  } catch {
    payload = { message: String(raw || '') };
  }
  handleEvent(name, payload);
}

/* ── state ─────────────────────────────────────────────────────────────── */

function applyState(payload, options = {}) {
  if (!payload) return;
  App.state = payload;
  App.sessions = payload.sessions || App.sessions || [];
  if (payload.session) App.session = payload.session;
  App.running = Boolean(payload.running);
  renderGlobalState();
  renderRecent();
  renderReadiness();
  if (App.route === 'settings' && (!App.settingsDirty || options.forceSettings)) {
    populateSettings();
  }
  if (App.route === 'activity') {
    loadAudit();
  }
}

function renderGlobalState() {
  const state = App.state;
  if (!state) return;
  const provider = state.provider || { label: 'OpenAI', model: 'gpt-4o-mini', configured: false };
  const settings = state.settings || {};
  const workspace = state.workspace || settings.workdir || '';

  $('#version-label').textContent = `v${state.version || '0.2.0'}`;
  $('#workspace-label').textContent = workspace || 'Select workspace';
  $('#workspace-label').title = workspace;
  $('#home-workspace').textContent = basename(workspace) || 'Workspace';
  $('#home-workspace').title = workspace;
  $('#chat-workspace').textContent = basename(workspace) || 'Workspace';
  $('#chat-workspace').title = workspace;
  if ($('#set-workdir-label')) $('#set-workdir-label').textContent = workspace || '—';
  if ($('#set-workdir')) $('#set-workdir').value = workspace;

  $('#provider-glyph').textContent = String(provider.label || 'M').charAt(0).toUpperCase();
  $('#provider-label').textContent = provider.label || 'Provider';
  $('#model-label').textContent = provider.model || '—';
  $('#home-provider').textContent = provider.label || 'Provider';
  $('#chat-provider').textContent = provider.label || 'Provider';
  $('#approval-mode').textContent = settings.auto_approve ? 'Auto-approve' : 'Ask first';

  const audit = state.audit || { ok: true, entries: 0, message: '' };
  $('#nav-audit-count').textContent = String(audit.entries || 0);
  $('#chat-audit-state').textContent = audit.ok ? 'Verified' : 'Broken';
  $('#chat-audit-state').style.color = audit.ok ? '' : 'var(--danger)';

  if (!App.running) setStatus('ready', 'Ready');
  renderProviderChip();
}

function renderProviderChip() {
  const state = App.state;
  if (!state) return;
  const provider = state.provider || {};
  const chip = $('#provider-chip');
  chip.classList.toggle('is-warning', Boolean(provider.configured === false));
  const dot = $('.provider-glyph', chip);
  if (dot) dot.title = provider.configured ? 'Key available' : 'No key configured';
}

function renderReadiness() {
  const state = App.state;
  if (!state) return;
  const provider = state.provider || {};
  const providers = state.providers || [];
  const row = providers.find((item) => item.id === provider.id) || {};
  const needsKey = Boolean(row.requires_key);
  const configured = Boolean(provider.configured);
  const providerReady = configured || !needsKey;

  const providerState = $('#ready-provider-state');
  const vaultState = $('#ready-vault-state');
  const auditState = $('#ready-audit-state');
  const vault = state.vault || {};
  const audit = state.audit || {};

  $('#ready-provider-detail').textContent = `${provider.label || 'Provider'} · ${provider.model || '—'}`;
  if (providerReady) {
    providerState.textContent = 'READY';
    providerState.className = 'readiness-state is-good';
    $('#ready-provider-dot').className = 'status-dot';
  } else {
    providerState.textContent = 'KEY NEEDED';
    providerState.className = 'readiness-state is-bad';
    $('#ready-provider-dot').className = 'status-dot is-bad';
  }

  $('#ready-vault-detail').textContent = vault.available
    ? `${vault.count || 0} sealed credential${(vault.count || 0) === 1 ? '' : 's'}`
    : 'Environment variables only';
  vaultState.textContent = vault.available ? 'DPAPI' : 'ENV';
  vaultState.className = `readiness-state ${vault.available ? 'is-good' : ''}`;

  $('#ready-audit-detail').textContent =
    audit.ok === false
      ? 'Chain broken · open the audit trail'
      : audit.entries
        ? `${audit.entries} entries verified`
        : 'No entries yet';
  auditState.textContent = audit.ok === false ? 'BROKEN' : 'VERIFIED';
  auditState.className = `readiness-state ${audit.ok === false ? 'is-bad' : 'is-good'}`;

  const score = [providerReady, Boolean(vault.available), audit.ok !== false].filter(Boolean).length;
  $('#readiness-score').textContent = `${score} / 3`;

  $('#vault-state').textContent = vault.available ? 'Vault ready' : 'Env fallback';
  $('#vault-state').className = `card-status ${vault.available ? 'secure' : ''}`;
  $('#vault-detail').textContent = vault.available
    ? `Windows DPAPI · ${vault.count || 0} item${(vault.count || 0) === 1 ? '' : 's'}`
    : 'DPAPI is unavailable on this platform';
  $('#vault-count').textContent = `${vault.count || 0} key${(vault.count || 0) === 1 ? '' : 's'}`;
  $('#settings-audit-detail').textContent =
    audit.ok === false
      ? 'Chain broken · inspect the audit trail'
      : audit.entries
        ? `${audit.entries} entries · chain verified`
        : 'No entries yet';
  $('#settings-audit-detail').style.color = audit.ok === false ? 'var(--danger)' : '';
}

function renderRecent() {
  const list = $('#recent-list');
  const empty = $('#recent-empty');
  if (!list) return;
  list.innerHTML = '';
  const sessions = App.sessions || [];
  empty.hidden = sessions.length > 0;
  for (const item of sessions.slice(0, 9)) {
    const button = el('button', 'recent-item');
    button.type = 'button';
    if (App.session && App.session.id === item.id) button.classList.add('is-active');
    const title = el('b', '', item.preview || 'Untitled operation');
    const meta = el('small', '', `${item.provider || 'provider'} · ${timeAgo(item.updated_at)}`);
    button.appendChild(title);
    button.appendChild(meta);
    button.title = item.preview || item.id;
    button.addEventListener('click', () => openSession(item.id));
    list.appendChild(button);
  }
}

/* ── routing ───────────────────────────────────────────────────────────── */

function setRoute(route, initial = false) {
  if (!['home', 'chat', 'activity', 'settings'].includes(route)) route = 'home';
  App.route = route;
  $$('.nav-item').forEach((item) => {
    item.classList.toggle('is-active', item.dataset.route === route);
  });
  $$('.view').forEach((view) => {
    view.classList.toggle('is-active', view.dataset.view === route);
  });
  if (!initial) {
    try {
      history.replaceState(null, '', `#${route}`);
    } catch {
      /* file:// may refuse history changes in some builds */
    }
  }
  if (route === 'activity') loadAudit();
  if (route === 'settings') {
    populateSettings();
    loadAudit(true);
  }
  if (route === 'chat') {
    renderChatShell();
    scrollTranscript();
  }
}

function renderChatShell() {
  if (!App.session) {
    $('#chat-title').textContent = 'Untitled operation';
    $('#chat-id').textContent = '—';
    $('#chat-meta').textContent = 'Mirsad will plan, act, and verify inside the selected workspace.';
    $('#session-id').textContent = '—';
    $('#session-created').textContent = '—';
    setChatStatus('ready', 'Ready');
    if (!$('#transcript').children.length) renderEmptyTranscript();
  } else {
    renderSessionHeader(App.session);
  }
}

function renderEmptyTranscript() {
  const transcript = $('#transcript');
  transcript.innerHTML = '';
  const box = el('div', 'transcript-empty');
  const mark = el('div', 'transcript-empty-mark');
  mark.innerHTML = '<svg aria-hidden="true"><use href="#i-command"/></svg>';
  const title = el('h3', '', 'A blank page, with a guardrail.');
  const copy = el(
    'p',
    '',
    'Describe the outcome you need. Mirsad will inspect the workspace, publish a plan, and ask before anything sensitive runs.'
  );
  const hint = el('span', 'mono', 'CTRL + ENTER FROM THE OVERVIEW');
  box.appendChild(mark);
  box.appendChild(title);
  box.appendChild(copy);
  box.appendChild(hint);
  transcript.appendChild(box);
}

/* ── home ──────────────────────────────────────────────────────────────── */

async function startFromHome() {
  const input = $('#home-input');
  const prompt = input.value.trim();
  if (!prompt) {
    input.focus();
    showToast('Describe the outcome you want Mirsad to produce.', 'warning');
    return;
  }
  if (App.running) {
    showToast('A run is already in progress. Stop it first.', 'warning');
    return;
  }
  if (!providerReady()) {
    showToast('Add an API key for this provider before starting a run.', 'warning');
    setRoute('settings');
    focusSoon('#key-input');
    return;
  }

  input.value = '';
  setRoute('chat');
  clearTranscript();
  App.session = null;
  App.renderedSessionId = null;
  resetOperation();
  renderChatShell();
  setStatus('working', 'Opening');
  setRunUi(true);
  $('#chat-title').textContent = prompt.length > 86 ? `${prompt.slice(0, 86)}…` : prompt;

  try {
    const created = await invoke('new_session');
    if (!created || !created.ok) {
      throw new Error((created && created.error) || 'Could not open a new operation.');
    }
    App.session = created.session;
    renderSessionHeader(created.session);
    const sent = await invoke('send_message', prompt);
    if (!sent || !sent.ok) {
      throw new Error((sent && sent.error) || 'The runtime rejected the brief.');
    }
  } catch (error) {
    setRunUi(false);
    setStatus('error', 'Needs attention');
    showToast(error.message || String(error), 'error');
    input.value = prompt;
    setRoute('home');
  }
}

function providerReady() {
  const state = App.state;
  if (!state) return true;
  const provider = state.provider || {};
  const row = (state.providers || []).find((item) => item.id === provider.id) || {};
  return Boolean(provider.configured) || row.requires_key === false;
}

/* ── chat ──────────────────────────────────────────────────────────────── */

function clearTranscript() {
  const transcript = $('#transcript');
  if (transcript) transcript.innerHTML = '';
}

function resetOperation() {
  App.plan = [];
  App.step = 0;
  App.totalSteps = 0;
  App.planCurrent = -1;
  App.tools = new Map();
  App.activity = [];
  renderPlan();
  renderActivity();
}

function renderSessionHeader(session) {
  if (!session) return;
  $('#chat-title').textContent = session.title || 'Untitled operation';
  $('#chat-id').textContent = session.id || '—';
  $('#session-id').textContent = session.id || '—';
  $('#session-created').textContent = shortDate(session.created_at);
  const providerRow = ((App.state && App.state.providers) || []).find(
    (item) => item.id === session.provider
  );
  const providerLabel = (providerRow && providerRow.label) || session.provider || 'Mirsad';
  $('#chat-meta').textContent = `${providerLabel} · ${session.model || 'default model'} · ${session.workdir || ''}`;
  if (session.plan && session.plan.length && !App.plan.length) {
    App.plan = session.plan;
    renderPlan();
  }
}

async function sendFromChat() {
  const input = $('#chat-input');
  const prompt = input.value.trim();
  if (!prompt) return;
  if (App.running) {
    showToast('A run is already in progress.', 'warning');
    return;
  }
  if (!providerReady()) {
    showToast('Add an API key for this provider before sending.', 'warning');
    setRoute('settings');
    focusSoon('#key-input');
    return;
  }
  input.value = '';
  input.style.height = '';
  try {
    const response = await invoke('send_message', prompt);
    if (!response || !response.ok) {
      throw new Error((response && response.error) || 'The runtime rejected the message.');
    }
  } catch (error) {
    input.value = prompt;
    showToast(error.message || String(error), 'error');
  }
}

async function cancelRun() {
  if (!App.running) return;
  notify('cancel_run');
  setStatus('working', 'Stopping');
  showToast('Stopping after the current step.', 'warning');
}

function setRunUi(running) {
  App.running = running;
  const stop = $('#chat-stop');
  const run = $('#chat-run');
  const homeRun = $('#home-run');
  if (stop) stop.hidden = !running;
  if (run) run.disabled = running;
  if (homeRun) homeRun.disabled = running;
  if (!running) {
    showTyping(false);
  }
}

function setStatus(kind, label) {
  App.lastStatus = label;
  const pill = $('#status-pill');
  const labelNode = $('#status-label');
  if (pill) {
    pill.classList.toggle('is-working', kind === 'working');
    pill.classList.toggle('is-error', kind === 'error');
  }
  if (labelNode) labelNode.textContent = label;
  setChatStatus(kind, label);
}

function setChatStatus(kind, label) {
  const chatStatus = $('#chat-status');
  if (!chatStatus) return;
  chatStatus.className = 'operation-status';
  if (kind === 'working') chatStatus.classList.add('is-working');
  if (kind === 'complete') chatStatus.classList.add('is-complete');
  if (kind === 'error') chatStatus.classList.add('is-error');
  chatStatus.innerHTML = '';
  const dot = el('span', 'status-dot');
  chatStatus.appendChild(dot);
  chatStatus.appendChild(el('span', '', label));
}

function showTyping(active, label) {
  const box = $('#typing');
  if (!box) return;
  box.hidden = !active;
  if (label) $('#typing-label').textContent = label;
  if (active) scrollTranscript();
}

function appendUserMessage(content) {
  const transcript = $('#transcript');
  const empty = $('.transcript-empty', transcript);
  if (empty) empty.remove();
  const message = el('article', 'message message-user');
  const meta = el('div', 'message-meta');
  meta.appendChild(el('span', '', 'BRIEF'));
  meta.appendChild(el('span', '', 'YOU'));
  const body = el('div', 'message-body', content);
  message.appendChild(meta);
  message.appendChild(body);
  transcript.appendChild(message);
  scrollTranscript();
}

function appendAssistantMessage(content, animate = true) {
  if (!content) return;
  const transcript = $('#transcript');
  const empty = $('.transcript-empty', transcript);
  if (empty) empty.remove();
  const message = el('article', `message message-assistant${animate ? '' : ' no-animate'}`);
  const head = el('div', 'assistant-head');
  const mark = el('span', 'assistant-mark');
  mark.innerHTML = '<svg aria-hidden="true"><use href="#i-dot"/></svg>';
  head.appendChild(mark);
  head.appendChild(el('span', '', 'MIRSAD'));
  head.appendChild(el('span', '', timeAgo(new Date().toISOString())));
  const body = el('div', 'markdown');
  body.innerHTML = renderMarkdown(content);
  message.appendChild(head);
  message.appendChild(body);
  transcript.appendChild(message);
  scrollTranscript();
}

function appendErrorNotice(message) {
  const transcript = $('#transcript');
  const box = el('div', 'message-error');
  const symbol = el('span', 'message-error-mark');
  symbol.innerHTML = '<svg aria-hidden="true"><use href="#i-alert"/></svg>';
  box.appendChild(symbol);
  box.appendChild(el('span', '', message));
  transcript.appendChild(box);
  scrollTranscript();
}

function scrollTranscript() {
  const transcript = $('#transcript');
  if (!transcript) return;
  window.requestAnimationFrame(() => {
    transcript.scrollTop = transcript.scrollHeight;
  });
}

/* ── tools ─────────────────────────────────────────────────────────────── */

function toolSummary(name, args) {
  if (!args) return '';
  if (name === 'run_command') return String(args.command || '');
  if (name === 'read_file' || name === 'write_file' || name === 'edit_file') {
    return String(args.path || '');
  }
  if (name === 'web_fetch') return String(args.url || '');
  if (name === 'web_search') return String(args.query || '');
  if (name === 'update_plan') return 'Publishing the flight plan';
  const first = Object.entries(args).find(([, value]) => typeof value === 'string');
  return first ? String(first[1]) : '';
}

function toolGlyph(name) {
  if (name === 'run_command') return 'i-terminal';
  if (name === 'read_file' || name === 'write_file' || name === 'edit_file') return 'i-file';
  if (name === 'web_search' || name === 'web_fetch') return 'i-search';
  return 'i-command';
}

function createToolCard(id, name, args, risk, summary) {
  const details = el('details', 'tool-card');
  details.dataset.toolId = id;
  const head = el('summary');
  const glyph = el('span', 'tool-glyph');
  glyph.innerHTML = `<svg aria-hidden="true"><use href="#${toolGlyph(name)}"/></svg>`;
  const nameNode = el('span', 'tool-name', name);
  const summaryNode = el('span', 'tool-summary', summary || toolSummary(name, args));
  const riskNode = el('span', `tool-risk ${risk === 'high' ? 'high' : ''}`, riskLabel(risk));
  const stateNode = el('span', 'tool-state is-running', 'Running');
  head.appendChild(glyph);
  head.appendChild(nameNode);
  head.appendChild(summaryNode);
  head.appendChild(riskNode);
  head.appendChild(stateNode);
  const output = el('pre', 'tool-output', 'Waiting for the tool to finish…');
  output.dataset.toolOutput = 'true';
  details.appendChild(head);
  details.appendChild(output);
  const transcript = $('#transcript');
  const empty = $('.transcript-empty', transcript);
  if (empty) empty.remove();
  transcript.appendChild(details);
  App.tools.set(id, {
    details,
    stateNode,
    output,
    name,
    arguments: args,
    risk,
    summary,
    status: 'running',
  });
  scrollTranscript();
  return details;
}

function looksFailed(result) {
  return /^(error|blocked|action denied)/i.test(String(result || '').trim());
}

function finishToolCard(id, name, result, failed) {
  let record = App.tools.get(id);
  if (!record) {
    record = { details: null, stateNode: null, output: null, name, status: 'done' };
  }
  record.status = failed ? 'failed' : 'done';
  if (record.details) {
    const stateNode = record.stateNode;
    if (stateNode) {
      stateNode.className = `tool-state ${failed ? 'is-failed' : ''}`;
      stateNode.textContent = failed ? 'Blocked' : 'Done';
    }
    const output = record.output;
    if (output) {
      output.textContent = result || '(no output)';
      output.classList.toggle('is-error', Boolean(failed));
    }
  }
  const activity = App.activity.find((item) => item.id === id);
  if (activity) {
    activity.status = failed ? 'failed' : 'done';
    renderActivity();
  }
}

function handleToolEvent(payload) {
  if (payload.phase === 'start') {
    if (payload.name === 'update_plan') return;
    const activity = {
      id: payload.id,
      name: payload.name,
      summary: payload.summary || toolSummary(payload.name, payload.arguments),
      status: 'running',
      risk: payload.risk || 'elevated',
    };
    App.activity.push(activity);
    renderActivity();
    createToolCard(
      payload.id,
      payload.name,
      payload.arguments || {},
      payload.risk,
      payload.summary
    );
    setStatus('working', 'Working');
  } else if (payload.phase === 'finish') {
    finishToolCard(payload.id, payload.name, payload.result, payload.failed);
  }
}

/* ── plan and activity ─────────────────────────────────────────────────── */

function renderPlan() {
  const list = $('#plan-list');
  const empty = $('#plan-empty');
  if (!list) return;
  list.innerHTML = '';
  const current = Math.min(App.step - 1, App.plan.length - 1);
  App.planCurrent = current;
  $('#plan-count').textContent = `${App.plan.length ? Math.min(App.step, App.plan.length) : 0} / ${App.plan.length}`;
  empty.hidden = App.plan.length > 0;
  App.plan.forEach((step, index) => {
    const row = el('div', 'plan-step');
    if (index < current) row.classList.add('is-done');
    if (index === current) row.classList.add('is-current');
    const number = el('span', 'plan-number', String(index + 1).padStart(2, '0'));
    const copy = el('span', '', step);
    row.appendChild(number);
    row.appendChild(copy);
    list.appendChild(row);
  });
}

function setPlan(steps, note) {
  App.plan = Array.isArray(steps) ? steps : [];
  renderPlan();
  if (note) showToast(note, 'info');
}

function renderActivity() {
  const list = $('#inspector-activity');
  const empty = $('#activity-empty');
  if (!list) return;
  list.innerHTML = '';
  empty.hidden = App.activity.length > 0;
  $('#activity-count').textContent = String(App.activity.length);
  for (const item of App.activity.slice(-8).reverse()) {
    const row = el('div', 'activity-row');
    if (item.status === 'running') row.classList.add('is-running');
    if (item.status === 'failed') row.classList.add('is-failed');
    const dot = el('span', 'activity-status');
    const copy = el('div', 'activity-copy');
    copy.appendChild(el('b', '', item.name));
    copy.appendChild(el('small', '', item.summary || item.status));
    row.appendChild(dot);
    row.appendChild(copy);
    list.appendChild(row);
  }
}

/* ── session loading and history ───────────────────────────────────────── */

async function openSession(sessionId) {
  if (App.running) {
    showToast('Stop the current run before opening another operation.', 'warning');
    return;
  }
  try {
    const response = await invoke('load_session', sessionId);
    if (!response || !response.ok) {
      throw new Error((response && response.error) || 'Could not open the operation.');
    }
    App.session = response.session;
    App.sessions = (App.state && App.state.sessions) || App.sessions;
    renderSession(response.session);
    setRoute('chat');
    renderRecent();
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

function renderSession(session) {
  App.session = session;
  App.renderedSessionId = session.id;
  resetOperation();
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const lastMessage = messages.length ? messages[messages.length - 1] : null;
  App.plan = Array.isArray(session.plan) ? session.plan.slice() : [];
  App.step = lastMessage && lastMessage.role === 'assistant' ? App.plan.length : 0;
  renderPlan();
  renderSessionHeader(session);
  if (lastMessage && lastMessage.role === 'assistant') setChatStatus('complete', 'Complete');
  else setChatStatus('ready', 'Ready');
  clearTranscript();
  const toolResults = new Map();
  const callIds = new Set();
  for (const message of messages) {
    if (message.role === 'tool' && message.tool_call_id) {
      toolResults.set(message.tool_call_id, message.content || '');
    }
  }
  for (const message of messages) {
    if (message.role === 'user') {
      appendUserMessage(message.content || '');
    } else if (message.role === 'assistant') {
      if (message.content) appendAssistantMessage(message.content, false);
      const calls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
      for (const call of calls) {
        const fn = call.function || {};
        const id = call.id || `${session.id}-${App.tools.size}`;
        if (callIds.has(id)) continue;
        callIds.add(id);
        let args = {};
        try {
          args = typeof fn.arguments === 'string' ? JSON.parse(fn.arguments) : fn.arguments || {};
        } catch {
          args = {};
        }
        if (fn.name === 'update_plan') continue;
        const result = toolResults.get(id);
        createToolCard(id, fn.name || 'tool', args, 'elevated', toolSummary(fn.name, args));
        if (result != null) finishToolCard(id, fn.name || 'tool', result, looksFailed(result));
      }
    }
  }
  App.activity = [];
  for (const [id, record] of App.tools.entries()) {
    App.activity.push({
      id,
      name: record.name,
      summary: record.summary || toolSummary(record.name, record.arguments),
      status: record.status || 'done',
    });
  }
  renderActivity();
  if (!messages.length) renderEmptyTranscript();
  scrollTranscript();
}

/* ── audit ─────────────────────────────────────────────────────────────── */

async function loadAudit(quiet = false) {
  if (!App.connected && !App.demo) return;
  try {
    const response = await invoke('audit_entries');
    if (!response || !response.ok) return;
    App.audit = response.entries || [];
    App.auditCheck = response.check || null;
    renderAudit();
    if (!quiet) renderGlobalState();
  } catch (error) {
    if (!quiet) showToast(error.message || String(error), 'error');
  }
}

function renderAudit() {
  const check = App.auditCheck;
  const audit = (App.state && App.state.audit) || {};
  const ok = check ? check.ok : audit.ok !== false;
  const entries = check ? check.entries : audit.entries || 0;
  const message =
    (check && check.message) ||
    audit.message ||
    (entries ? `${entries} entries verified.` : 'No activity recorded yet.');

  $('#audit-seal').classList.toggle('is-bad', !ok);
  $('#audit-status').textContent = ok ? (entries ? 'Chain verified' : 'No activity recorded') : 'Chain integrity broken';
  $('#audit-message').textContent = message;
  $('#audit-count').textContent = String(entries);
  $('#nav-audit-count').textContent = String(entries);
  $('#ready-audit-detail').textContent = ok
    ? entries
      ? `${entries} entries verified`
      : 'No entries yet'
    : 'Chain broken · open the audit trail';
  $('#ready-audit-state').textContent = ok ? 'VERIFIED' : 'BROKEN';
  $('#ready-audit-state').className = `readiness-state ${ok ? 'is-good' : 'is-bad'}`;
  $('#chat-audit-state').textContent = ok ? 'Verified' : 'Broken';
  $('#settings-audit-detail').textContent = ok
    ? entries
      ? `${entries} entries · chain verified`
      : 'No entries yet'
    : 'Chain broken · inspect the audit trail';
  $('#settings-audit-detail').style.color = ok ? '' : 'var(--danger)';

  const list = $('#audit-list');
  const empty = $('#audit-empty');
  if (!list) return;
  list.innerHTML = '';
  empty.hidden = App.audit.length > 0;
  for (const entry of App.audit) {
    const row = el('div', 'ledger-row');
    row.appendChild(el('span', 'ledger-seq', `#${padSequence(entry.seq)}`));
    row.appendChild(el('span', 'ledger-time', `${clockTime(entry.ts)}`));
    row.appendChild(el('span', 'ledger-event', String(entry.event || 'event')));
    row.appendChild(el('span', 'ledger-detail', String(entry.summary || '')));
    row.appendChild(el('span', 'ledger-hash', String(entry.hash || '').slice(0, 12)));
    list.appendChild(row);
  }
}

async function verifyAudit() {
  try {
    const response = await invoke('verify_audit');
    if (!response) return;
    App.auditCheck = {
      ok: response.ok,
      entries: response.entries,
      message: response.message,
      broken_at: response.broken_at,
    };
    if (App.state && App.state.audit) {
      App.state.audit = {
        ...App.state.audit,
        ok: response.ok,
        entries: response.entries,
        message: response.message,
      };
    }
    renderAudit();
    renderGlobalState();
    showToast(
      response.ok
        ? `Audit chain verified · ${response.entries} entries.`
        : `Audit chain broken at line ${response.broken_at || '?'}.`,
      response.ok ? 'success' : 'error'
    );
    await loadAudit(true);
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

/* ── settings ──────────────────────────────────────────────────────────── */

function populateSettings() {
  const state = App.state;
  if (!state) return;
  const settings = state.settings || {};
  const providers = state.providers || [];
  const select = $('#set-provider');
  if (select && !select.options.length) {
    for (const provider of providers) {
      const option = document.createElement('option');
      option.value = provider.id;
      option.textContent = provider.label;
      select.appendChild(option);
    }
  }
  if (select) select.value = settings.provider || (state.provider && state.provider.id) || 'openai';
  $('#set-model').value = settings.model || '';
  $('#set-temperature').value = String(settings.temperature ?? 0.2);
  $('#temp-value').textContent = Number(settings.temperature ?? 0.2).toFixed(1);
  $('#set-max-steps').value = String(settings.max_steps ?? 12);
  $('#set-max-history').value = String(settings.max_history ?? 80);
  $('#set-auto').checked = Boolean(settings.auto_approve);
  $('#auto-warning').hidden = !settings.auto_approve;
  $('#set-workdir').value = settings.workdir || state.workspace || '';
  $('#set-workdir-label').textContent = settings.workdir || state.workspace || '—';
  App.settingsDirty = false;
  updateProviderSettings();
}

function updateProviderSettings() {
  const state = App.state;
  if (!state) return;
  const providerId = $('#set-provider').value;
  const provider = (state.providers || []).find((item) => item.id === providerId) || {};
  const configured = Boolean(provider.configured);
  const requiresKey = provider.requires_key !== false;
  const keyStatus = $('#key-status');
  if (!requiresKey) {
    keyStatus.textContent = 'No key needed';
    keyStatus.className = 'card-status secure';
  } else if (configured) {
    keyStatus.textContent = 'Key ready';
    keyStatus.className = 'card-status secure';
  } else {
    keyStatus.textContent = 'Key missing';
    keyStatus.className = 'card-status';
  }
  $('#provider-note').textContent = provider.note || 'Keys are sealed with Windows DPAPI and never written to config.json.';
  $('#key-env').textContent = provider.env_key || '—';
  $('#set-model').placeholder = provider.default_model || 'Provider default';
  $('#key-dot').className = `status-dot ${requiresKey ? (configured ? '' : 'is-bad') : ''}`;
  $('#key-detail').textContent = !requiresKey
    ? 'This provider runs locally and needs no API key.'
    : configured
      ? 'A credential is available to the runtime for this provider.'
      : 'No key in the encrypted vault. Add one below or use the environment.';
  $('#remove-key').disabled = !requiresKey || !configured;
  $('#save-key').disabled = !requiresKey;

  const vaultNames = ((state.vault && state.vault.secrets) || []).map((item) => item.name);
  const stored = provider.env_key && vaultNames.includes(provider.env_key);
  $('#ready-vault-detail').textContent = state.vault && state.vault.available
    ? `${state.vault.count || 0} sealed credential${(state.vault.count || 0) === 1 ? '' : 's'}`
    : 'Environment variables only';
  if (stored) $('#key-detail').textContent = 'Sealed in the Windows DPAPI vault.';
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    provider: $('#set-provider').value,
    model: $('#set-model').value.trim(),
    temperature: Number($('#set-temperature').value),
    max_steps: Number($('#set-max-steps').value),
    max_history: Number($('#set-max-history').value),
    auto_approve: $('#set-auto').checked,
    workdir: $('#set-workdir').value,
  };
  try {
    const response = await invoke('save_settings', JSON.stringify(payload));
    if (!response || !response.ok) {
      throw new Error((response && response.error) || 'Could not save settings.');
    }
    App.settingsDirty = false;
    if (response.state) applyState(response.state, { forceSettings: true });
    else await refreshState();
    const provider = (App.state.providers || []).find((item) => item.id === payload.provider);
    if (provider && provider.requires_key && !provider.configured) {
      showToast('Control surface saved. Add the provider key to start a run.', 'warning');
    }
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

async function saveApiKey() {
  const providerId = $('#set-provider').value;
  const input = $('#key-input');
  const key = input.value.trim();
  if (!key) {
    input.focus();
    showToast('Paste an API key first.', 'warning');
    return;
  }
  try {
    const response = await invoke('save_api_key', providerId, key);
    if (!response || !response.ok) {
      throw new Error((response && response.error) || 'Could not save the key.');
    }
    input.value = '';
    if (response.state) applyState(response.state);
    else await refreshState();
    updateProviderSettings();
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

async function removeApiKey() {
  const providerId = $('#set-provider').value;
  const provider = (App.state.providers || []).find((item) => item.id === providerId) || {};
  const confirmed = window.confirm(
    `Remove the stored ${provider.label || providerId} key? The provider will stop working until another key is supplied.`
  );
  if (!confirmed) return;
  try {
    const response = await invoke('remove_api_key', providerId);
    if (!response || !response.ok) {
      throw new Error((response && response.error) || 'Could not remove the key.');
    }
    if (response.state) applyState(response.state);
    else await refreshState();
    updateProviderSettings();
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

async function pickWorkspace() {
  try {
    const response = await invoke('choose_workspace');
    if (!response || !response.ok) return;
    $('#set-workdir').value = response.path;
    $('#set-workdir-label').textContent = response.path;
    App.settingsDirty = true;
    setRoute('settings');
    showToast('Workspace staged. Save the control surface to apply it.', 'info');
  } catch (error) {
    showToast(error.message || String(error), 'error');
  }
}

async function refreshState() {
  try {
    const response = await invoke('get_state');
    if (response && response.ok) applyState(response.state);
  } catch {
    /* state refresh is best effort */
  }
}

/* ── command palette ───────────────────────────────────────────────────── */

function commandList() {
  const commands = [
    {
      id: 'new',
      label: 'New operation',
      hint: 'Ctrl N',
      icon: 'i-plus',
      run: () => startNewDraft(),
    },
    {
      id: 'home',
      label: 'Go to overview',
      hint: 'Ctrl 1',
      icon: 'i-home',
      run: () => setRoute('home'),
    },
    {
      id: 'chat',
      label: 'Open current operation',
      hint: 'Ctrl 2',
      icon: 'i-command',
      run: () => setRoute('chat'),
    },
    {
      id: 'activity',
      label: 'Open audit trail',
      hint: 'Ctrl 3',
      icon: 'i-activity',
      run: () => setRoute('activity'),
    },
    {
      id: 'settings',
      label: 'Open control surface',
      hint: 'Ctrl 4',
      icon: 'i-settings',
      run: () => setRoute('settings'),
    },
    {
      id: 'workspace',
      label: 'Choose workspace',
      hint: 'Folder',
      icon: 'i-folder',
      run: () => pickWorkspace(),
    },
    {
      id: 'verify',
      label: 'Verify audit chain',
      hint: 'SHA-256',
      icon: 'i-shield',
      run: () => verifyAudit(),
    },
  ];
  if (App.running) {
    commands.unshift({
      id: 'stop',
      label: 'Stop the current run',
      hint: 'Cancel',
      icon: 'i-stop',
      run: () => cancelRun(),
    });
  }
  const sessions = (App.sessions || []).slice(0, 6).map((item) => ({
    id: `session:${item.id}`,
    label: item.preview || 'Untitled operation',
    hint: item.provider || 'session',
    icon: 'i-clock',
    run: () => openSession(item.id),
  }));
  return [...commands, ...sessions];
}

function openCommandPalette() {
  const overlay = $('#command-overlay');
  overlay.hidden = false;
  const input = $('#command-input');
  input.value = '';
  App.paletteIndex = 0;
  renderCommandList('');
  focusSoon('#command-input');
}

function closeCommandPalette() {
  $('#command-overlay').hidden = true;
}

function renderCommandList(query) {
  const list = $('#command-list');
  list.innerHTML = '';
  const normalized = query.trim().toLowerCase();
  App.paletteCommands = commandList().filter((command) => {
    if (!normalized) return true;
    return `${command.label} ${command.hint}`.toLowerCase().includes(normalized);
  });
  App.paletteIndex = Math.min(App.paletteIndex, Math.max(0, App.paletteCommands.length - 1));
  App.paletteCommands.forEach((command, index) => {
    const button = el('button', 'command-item');
    button.type = 'button';
    if (index === App.paletteIndex) button.classList.add('is-selected');
    button.innerHTML = `<svg aria-hidden="true"><use href="#${command.icon}"/></svg>`;
    button.appendChild(el('span', '', command.label));
    button.appendChild(el('small', '', command.hint || ''));
    button.addEventListener('click', () => runCommand(index));
    button.addEventListener('mouseenter', () => {
      App.paletteIndex = index;
      $$('.command-item', list).forEach((item, itemIndex) => {
        item.classList.toggle('is-selected', itemIndex === index);
      });
    });
    list.appendChild(button);
  });
  if (!App.paletteCommands.length) {
    const empty = el('div', 'command-empty', 'No matching action.');
    list.appendChild(empty);
  }
}

function runCommand(index) {
  const command = App.paletteCommands[index];
  if (!command) return;
  closeCommandPalette();
  command.run();
}

/* ── approvals ─────────────────────────────────────────────────────────── */

function queueApproval(request) {
  App.approvals.push(request);
  if (!App.activeApproval) showNextApproval();
}

function showNextApproval() {
  const request = App.approvals.shift();
  if (!request) {
    App.activeApproval = null;
    $('#modal-root').hidden = true;
    return;
  }
  App.activeApproval = request;
  $('#modal-root').hidden = false;
  $('#approval-risk').textContent = riskLabel(request.risk);
  $('#approval-risk').className = `risk-badge ${request.risk === 'high' ? 'high' : ''}`;
  $('#approval-tool').textContent = request.tool || 'tool';
  $('#approval-summary').textContent = request.summary || 'Review the payload before it runs.';
  $('#approval-detail').textContent = formatArguments(request.arguments);
  const reasons = $('#approval-reasons');
  reasons.innerHTML = '';
  for (const reason of request.reasons || []) reasons.appendChild(el('span', '', reason));
  $('#approval-allow').focus();
}

function resolveApproval(approved) {
  const request = App.activeApproval;
  if (!request) return;
  App.activeApproval = null;
  notify('resolve_approval', request.id, Boolean(approved));
  $('#modal-root').hidden = true;
  showToast(approved ? 'Action approved once and recorded.' : 'Action denied and recorded.', approved ? 'info' : 'warning');
  window.setTimeout(showNextApproval, 120);
}

function formatArguments(args) {
  if (args == null) return '(no arguments)';
  try {
    const serialized = JSON.stringify(args, null, 2);
    return serialized.length > 12000 ? `${serialized.slice(0, 12000)}\n… truncated in view` : serialized;
  } catch {
    return String(args);
  }
}

/* ── toasts ────────────────────────────────────────────────────────────── */

function showToast(message, kind = 'info') {
  const stack = $('#toast-stack');
  if (!stack) return;
  const toast = el('div', `toast is-${kind}`);
  const mark = el('span', 'toast-mark');
  const iconName = kind === 'error' ? 'i-alert' : kind === 'warning' ? 'i-alert' : 'i-check';
  mark.innerHTML = `<svg aria-hidden="true"><use href="#${iconName}"/></svg>`;
  toast.appendChild(mark);
  toast.appendChild(el('span', '', message));
  stack.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add('is-leaving');
    window.setTimeout(() => toast.remove(), 220);
  }, kind === 'error' ? 7000 : 4300);
}

/* ── markdown ──────────────────────────────────────────────────────────── */

function renderMarkdown(source) {
  const token = `MIRSDTOKEN${Math.random().toString(36).slice(2)}`;
  const blocks = [];
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
  let inFence = false;
  let fenceLanguage = '';
  let fenceLines = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];
  let html = '';

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html += `<p>${inlineMarkdown(paragraph.join(' '), token, blocks)}</p>`;
    paragraph = [];
  };
  const flushList = () => {
    if (!listType) return;
    const tag = listType;
    html += `<${tag}>${listItems.map((item) => `<li>${inlineMarkdown(item, token, blocks)}</li>`).join('')}</${tag}>`;
    listType = null;
    listItems = [];
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  for (const raw of lines) {
    if (raw.startsWith('```')) {
      if (inFence) {
        const code = escapeHtml(fenceLines.join('\n'));
        blocks.push(`<pre><code${fenceLanguage ? ` data-language="${escapeHtml(fenceLanguage)}"` : ''}>${code}</code></pre>`);
        html += `${token}BLOCK${blocks.length - 1}${token}`;
        inFence = false;
        fenceLanguage = '';
        fenceLines = [];
      } else {
        flushAll();
        inFence = true;
        fenceLanguage = raw.slice(3).trim();
      }
      continue;
    }
    if (inFence) {
      fenceLines.push(raw);
      continue;
    }
    if (!raw.trim()) {
      flushAll();
      continue;
    }
    if (raw.startsWith('### ')) {
      flushAll();
      html += `<h3>${inlineMarkdown(raw.slice(4), token, blocks)}</h3>`;
      continue;
    }
    if (raw.startsWith('## ')) {
      flushAll();
      html += `<h2>${inlineMarkdown(raw.slice(3), token, blocks)}</h2>`;
      continue;
    }
    if (raw.startsWith('# ')) {
      flushAll();
      html += `<h1>${inlineMarkdown(raw.slice(2), token, blocks)}</h1>`;
      continue;
    }
    if (raw.startsWith('> ')) {
      flushAll();
      html += `<blockquote>${inlineMarkdown(raw.slice(2), token, blocks)}</blockquote>`;
      continue;
    }
    const ordered = raw.match(/^\s*\d+\.\s+(.*)$/);
    const unordered = raw.match(/^\s*[-*]\s+(.*)$/);
    if (ordered || unordered) {
      flushParagraph();
      const type = ordered ? 'ol' : 'ul';
      if (listType && listType !== type) flushList();
      listType = type;
      listItems.push((ordered || unordered)[1]);
      continue;
    }
    flushList();
    paragraph.push(raw.trim());
  }
  if (inFence) {
    const code = escapeHtml(fenceLines.join('\n'));
    blocks.push(`<pre><code>${code}</code></pre>`);
    html += `${token}BLOCK${blocks.length - 1}${token}`;
  }
  flushAll();
  html = html.replace(new RegExp(`${token}BLOCK(\\d+)${token}`, 'g'), (_, index) => blocks[Number(index)] || '');
  return html;
}

function inlineMarkdown(value, token, blocks) {
  let result = escapeHtml(value);
  const codes = [];
  result = result.replace(/`([^`]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`);
    return `${token}CODE${codes.length - 1}${token}`;
  });
  result = result.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => {
    return `<a href="#" data-external="${escapeHtml(url)}">${label}</a>`;
  });
  result = result.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  result = result.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  result = result.replace(new RegExp(`${token}CODE(\\d+)${token}`, 'g'), (_, index) => codes[Number(index)] || '');
  return result;
}

/* ── static events ─────────────────────────────────────────────────────── */

function bindStaticEvents() {
  document.addEventListener('click', (event) => {
    const routeButton = event.target.closest('[data-route]');
    if (routeButton) {
      event.preventDefault();
      setRoute(routeButton.dataset.route);
      return;
    }
    const suggestion = event.target.closest('[data-prompt]');
    if (suggestion) {
      const input = $('#home-input');
      input.value = suggestion.dataset.prompt;
      setRoute('home');
      focusSoon('#home-input');
      return;
    }
    const external = event.target.closest('[data-external]');
    if (external && external.dataset.external) {
      event.preventDefault();
      notify('open_external', external.dataset.external);
      return;
    }
  });

  $('#brand-home').addEventListener('click', () => setRoute('home'));
  $('#btn-new').addEventListener('click', startNewDraft);
  $('#command-trigger').addEventListener('click', openCommandPalette);
  $('#workspace-chip').addEventListener('click', pickWorkspace);
  $('#provider-chip').addEventListener('click', () => setRoute('settings'));

  $('#home-composer').addEventListener('submit', (event) => {
    event.preventDefault();
    startFromHome();
  });
  $('#home-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      startFromHome();
    }
  });
  $('#home-input').addEventListener('input', () => {
    const input = $('#home-input');
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 210)}px`;
  });

  $('#chat-composer').addEventListener('submit', (event) => {
    event.preventDefault();
    sendFromChat();
  });
  $('#chat-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendFromChat();
    }
  });
  $('#chat-input').addEventListener('input', () => {
    const input = $('#chat-input');
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
  });
  $('#chat-stop').addEventListener('click', cancelRun);

  $('#verify-audit').addEventListener('click', verifyAudit);
  $('#refresh-audit').addEventListener('click', () => loadAudit());
  $('#settings-verify').addEventListener('click', verifyAudit);

  $('#settings-form').addEventListener('submit', saveSettings);
  $('#settings-form').addEventListener('input', () => {
    App.settingsDirty = true;
  });
  $('#set-provider').addEventListener('change', () => {
    App.settingsDirty = true;
    $('#set-model').value = '';
    updateProviderSettings();
  });
  $('#set-temperature').addEventListener('input', () => {
    $('#temp-value').textContent = Number($('#set-temperature').value).toFixed(1);
  });
  $('#set-auto').addEventListener('change', () => {
    $('#auto-warning').hidden = !$('#set-auto').checked;
  });
  $('#browse-workdir').addEventListener('click', pickWorkspace);
  $('#save-key').addEventListener('click', saveApiKey);
  $('#remove-key').addEventListener('click', removeApiKey);
  $('#key-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      saveApiKey();
    }
  });

  $('#command-overlay').addEventListener('click', (event) => {
    if (event.target === $('#command-overlay')) closeCommandPalette();
  });
  $('#command-input').addEventListener('input', (event) => {
    App.paletteIndex = 0;
    renderCommandList(event.target.value);
  });
  $('#command-input').addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      App.paletteIndex = Math.min(App.paletteIndex + 1, App.paletteCommands.length - 1);
      updatePaletteSelection();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      App.paletteIndex = Math.max(App.paletteIndex - 1, 0);
      updatePaletteSelection();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      runCommand(App.paletteIndex);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      closeCommandPalette();
    }
  });

  $('#approval-deny').addEventListener('click', () => resolveApproval(false));
  $('#approval-allow').addEventListener('click', () => resolveApproval(true));
  $('#modal-root').addEventListener('click', (event) => {
    if (event.target.classList.contains('modal-scrim')) resolveApproval(false);
  });

  document.addEventListener('keydown', (event) => {
    const inInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement && document.activeElement.tagName);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openCommandPalette();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') {
      event.preventDefault();
      startNewDraft();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && ['1', '2', '3', '4'].includes(event.key)) {
      event.preventDefault();
      setRoute({ 1: 'home', 2: 'chat', 3: 'activity', 4: 'settings' }[event.key]);
      return;
    }
    if (event.key === 'Escape') {
      if (!$('#command-overlay').hidden) {
        closeCommandPalette();
        return;
      }
      if (!$('#modal-root').hidden && App.activeApproval) {
        resolveApproval(false);
        return;
      }
      if (document.activeElement && document.activeElement.blur && !inInput) document.activeElement.blur();
    }
  });
}

function updatePaletteSelection() {
  $$('.command-item').forEach((item, index) => {
    item.classList.toggle('is-selected', index === App.paletteIndex);
  });
  const selected = $$('.command-item')[App.paletteIndex];
  if (selected) selected.scrollIntoView({ block: 'nearest' });
}

/* ── events from Python ────────────────────────────────────────────────── */

function handleEvent(name, payload) {
  switch (name) {
    case 'state':
      applyState(payload);
      break;
    case 'sessions':
      App.sessions = payload.sessions || [];
      if (App.state) App.state.sessions = App.sessions;
      renderRecent();
      break;
    case 'session':
      if (payload && payload.id === null) {
        App.session = null;
        App.renderedSessionId = null;
        renderChatShell();
      } else if (payload && payload.id) {
        App.session = payload;
        renderSessionHeader(payload);
        if (App.route === 'chat' && payload.messages && App.renderedSessionId !== payload.id) {
          renderSession(payload);
        }
      }
      break;
    case 'session.header':
      if (!App.session) App.session = { id: payload.id };
      App.session.id = payload.id;
      App.session.title = payload.title;
      App.session.provider = payload.provider;
      App.session.model = payload.model;
      App.session.workdir = payload.workdir;
      App.renderedSessionId = payload.id;
      renderSessionHeader(App.session);
      break;
    case 'session.sync':
      if (payload && payload.id) {
        const wasSame = App.session && App.session.id === payload.id;
        App.session = payload;
        if (wasSame) {
          $('#chat-title').textContent = payload.title || 'Untitled operation';
          $('#chat-id').textContent = payload.id;
          $('#session-id').textContent = payload.id;
          $('#session-created').textContent = shortDate(payload.created_at);
          if (payload.plan && payload.plan.length) {
            App.plan = payload.plan;
            renderPlan();
          }
        }
      }
      break;
    case 'user': {
      const content = payload.content || '';
      const currentTitle = ($('#chat-title').textContent || '').trim();
      if (!currentTitle || currentTitle === 'Untitled operation') {
        $('#chat-title').textContent =
          content.length > 86 ? `${content.slice(0, 86)}…` : content;
      }
      appendUserMessage(content);
      if (App.route !== 'chat') setRoute('chat');
      break;
    }
    case 'assistant':
      appendAssistantMessage(payload.content || '');
      break;
    case 'tool':
      handleToolEvent(payload);
      break;
    case 'plan':
      setPlan(payload.steps || [], payload.note || '');
      break;
    case 'step':
      App.step = payload.current || App.step;
      App.totalSteps = payload.total || App.totalSteps;
      renderPlan();
      if (payload.current && payload.total) {
        showTyping(true, `Mirsad is thinking — step ${payload.current} of ${payload.total}`);
      }
      break;
    case 'typing':
      showTyping(Boolean(payload.active), payload.label || '');
      break;
    case 'run':
      handleRunState(payload);
      break;
    case 'error':
      appendErrorNotice(payload.message || 'The run failed.');
      setStatus('error', 'Needs attention');
      setRunUi(false);
      showToast(payload.message || 'The run failed.', 'error');
      break;
    case 'audit':
      if (App.state) App.state.audit = payload;
      renderGlobalState();
      loadAudit(true);
      break;
    case 'toast':
      showToast(payload.message || '', payload.kind || 'info');
      break;
    case 'approval.requested':
      queueApproval(payload);
      break;
    case 'approval.resolved':
      App.approvals = App.approvals.filter((item) => item.id !== payload.id);
      if (App.activeApproval && App.activeApproval.id === payload.id) {
        App.activeApproval = null;
        $('#modal-root').hidden = true;
        window.setTimeout(showNextApproval, 80);
      }
      break;
    default:
      break;
  }
}

function handleRunState(payload) {
  const state = payload.state;
  if (state === 'running') {
    setRunUi(true);
    setStatus('working', 'Working');
    App.activity = [];
    renderActivity();
  } else if (state === 'stopping') {
    setStatus('working', 'Stopping');
    setRunUi(true);
  } else if (state === 'complete') {
    setRunUi(false);
    setStatus('complete', 'Complete');
    refreshState();
    if (App.route === 'activity') loadAudit(true);
  } else if (state === 'cancelled') {
    setRunUi(false);
    setStatus('ready', 'Stopped');
    refreshState();
  } else if (state === 'error') {
    setRunUi(false);
    setStatus('error', 'Needs attention');
    refreshState();
  }
}

function startNewDraft() {
  if (App.running) {
    showToast('Finish or stop the current run first.', 'warning');
    return;
  }
  App.session = null;
  App.renderedSessionId = null;
  resetOperation();
  clearTranscript();
  renderChatShell();
  renderEmptyTranscript();
  setRoute('chat');
  focusSoon('#chat-input');
}

/* ── demo / preview mode ───────────────────────────────────────────────── */

function buildDemoShell() {
  if (!document.body.classList.contains('is-booting')) {
    document.body.classList.add('is-booting');
  }
}

function enterDemo() {
  if (App.demo) return;
  App.demo = true;
  App.connected = false;
  App.demoListeners = [onBridgeEvent];
  const demo = demoData();
  App.demoData = demo;
  App.state = demo.state;
  App.sessions = demo.state.sessions;
  App.session = demo.session;
  renderGlobalState();
  renderRecent();
  renderReadiness();
  populateSettings();
  if (App.session) renderSession(App.session);
  if (App.route === 'activity') loadAudit();
  if (new URLSearchParams(window.location.search).get('approval') === '1') {
    queueApproval(demo.approval);
  }
  finishBoot();
}

function demoEmit(name, payload) {
  for (const listener of App.demoListeners) {
    listener(name, JSON.stringify(payload));
  }
}

function nowIso(offsetSeconds = 0) {
  return new Date(Date.now() - offsetSeconds * 1000).toISOString();
}

function demoData() {
  const workdir = 'C:\\Users\\Mirsad\\Work\\atlas-api';
  const sessionId = '20260309-142210-a91c';
  const audit = demoAudit();
  const messages = [
    {
      role: 'user',
      content:
        'Audit the public API for abuse paths, add tenant-aware rate limiting, and prove it with tests. Preserve every existing response shape.',
    },
    {
      role: 'assistant',
      content:
        "I'll map the request lifecycle first, then narrow the policy change to the middleware layer so the public contract stays untouched.",
      tool_calls: [
        {
          id: 'call_map_1',
          type: 'function',
          function: { name: 'list_files', arguments: JSON.stringify({ path: 'src', recursive: true }) },
        },
        {
          id: 'call_map_2',
          type: 'function',
          function: { name: 'read_file', arguments: JSON.stringify({ path: 'src/server.ts' }) },
        },
      ],
    },
    {
      role: 'tool',
      tool_call_id: 'call_map_1',
      name: 'list_files',
      content:
        'src/server.ts\nsrc/middleware/auth.ts\nsrc/middleware/errors.ts\nsrc/routes/accounts.ts\nsrc/routes/transfers.ts\nsrc/routes/webhooks.ts\ntest/api.test.ts',
    },
    {
      role: 'tool',
      tool_call_id: 'call_map_2',
      name: 'read_file',
      content:
        'import express from "express";\nimport { auth } from "./middleware/auth";\n...\napp.use("/v1", routes);\napp.listen(PORT);',
    },
    {
      role: 'assistant',
      content:
        'The surface is small and the routing order is clear. The risk is concentrated in `src/routes/transfers.ts` and `src/routes/webhooks.ts`: both accept high-volume writes before authentication completes. I’m going to read those and the test harness.',
      tool_calls: [
        {
          id: 'call_audit_1',
          type: 'function',
          function: { name: 'read_file', arguments: JSON.stringify({ path: 'src/routes/transfers.ts' }) },
        },
        {
          id: 'call_audit_2',
          type: 'function',
          function: { name: 'read_file', arguments: JSON.stringify({ path: 'test/api.test.ts' }) },
        },
      ],
    },
    {
      role: 'tool',
      tool_call_id: 'call_audit_1',
      name: 'read_file',
      content:
        'router.post("/transfers", async (req, res) => {\n  const { tenantId, amount } = req.body;\n  // no limiter, no idempotency key\n  return transferService.create(tenantId, amount);\n});',
    },
    {
      role: 'tool',
      tool_call_id: 'call_audit_2',
      name: 'read_file',
      content:
        'describe("POST /v1/transfers", () => {\n  it("returns 201 for a valid transfer", ...);\n  it("rejects an invalid amount", ...);\n});',
    },
    {
      role: 'assistant',
      content:
        'The middleware is the right seam: the route contract stays intact, and the limiter can key on the verified tenant after `auth` runs. I’ll add a token bucket with an in-memory adapter, wire it before the route handlers, then add burst and sustained-traffic tests.',
      tool_calls: [
        {
          id: 'call_write_1',
          type: 'function',
          function: {
            name: 'write_file',
            arguments: JSON.stringify({
              path: 'src/middleware/rate-limit.ts',
              content:
                'export function rateLimit({ capacity, refillPerSecond }) {\n  const buckets = new Map();\n  return (req, res, next) => {\n    const key = req.auth?.tenantId ?? req.ip;\n    const now = Date.now();\n    const bucket = buckets.get(key) ?? { tokens: capacity, at: now };\n    bucket.tokens = Math.min(capacity, bucket.tokens + ((now - bucket.at) / 1000) * refillPerSecond);\n    bucket.at = now;\n    if (bucket.tokens < 1) return res.status(429).json({ error: "rate_limited" });\n    bucket.tokens -= 1;\n    buckets.set(key, bucket);\n    next();\n  };\n}\n',
            }),
          },
        },
      ],
    },
    {
      role: 'tool',
      tool_call_id: 'call_write_1',
      name: 'write_file',
      content: 'Wrote 18 lines to src/middleware/rate-limit.ts.',
    },
    {
      role: 'assistant',
      content:
        'The limiter is in place and keyed by verified tenant. Now I’m running the existing suite first so a regression is attributable, then the new burst test.',
      tool_calls: [
        {
          id: 'call_test_1',
          type: 'function',
          function: {
            name: 'run_command',
            arguments: JSON.stringify({ command: 'npm test -- --runInBand', cwd: '.' }),
          },
        },
      ],
    },
    {
      role: 'tool',
      tool_call_id: 'call_test_1',
      name: 'run_command',
      content:
        'PASS test/api.test.ts\n  POST /v1/transfers\n    ✓ returns 201 for a valid transfer (41 ms)\n    ✓ rejects an invalid amount (8 ms)\n  POST /v1/webhooks\n    ✓ verifies the signature (12 ms)\n\nTest Suites: 1 passed, 1 total\nTests:       3 passed, 3 total\nTime:        2.184 s',
    },
    {
      role: 'assistant',
      content:
        'The regression suite is green. The limiter is wired and the response shape is unchanged.\n\n## What changed\n\n- Added a tenant-aware token bucket at `src/middleware/rate-limit.ts`.\n- Mounted it after `auth` and before the transfer and webhook routers.\n- Added burst coverage plus a sustained-traffic regression test.\n\n## Residual risk\n\n- The bucket is process-local. A multi-instance deployment needs a shared counter (Redis or the platform limiter).\n- Webhook verification still happens before the limiter; a signature flood can consume CPU. I left that path untouched to avoid changing the webhook contract.\n\n**Recommended next step:** move the bucket to the shared store and add a load test at the edge.',
    },
  ];

  const session = {
    id: sessionId,
    title: 'Harden the public API edge',
    created_at: nowIso(540),
    updated_at: nowIso(38),
    provider: 'openai',
    model: 'gpt-4o-mini',
    workdir,
    plan: [
      'Map the request lifecycle and middleware order.',
      'Identify unauthenticated routes and trust boundaries.',
      'Add a tenant-aware token bucket without changing response shapes.',
      'Write burst and sustained-traffic regression tests.',
      'Run the suite and summarize the residual risk.',
    ],
    messages,
  };

  const state = {
    app: 'Mirsad Studio',
    version: '0.2.0',
    workspace: workdir,
    config_file: 'C:\\Users\\Mirsad\\.mirsad\\config.json',
    provider: { id: 'openai', label: 'OpenAI', model: 'gpt-4o-mini', configured: true },
    settings: {
      provider: 'openai',
      model: '',
      temperature: 0.2,
      max_steps: 12,
      max_history: 80,
      auto_approve: false,
      workdir,
    },
    providers: [
      { id: 'openai', label: 'OpenAI', model: 'gpt-4o-mini', default_model: 'gpt-4o-mini', env_key: 'OPENAI_API_KEY', requires_key: true, configured: true, note: 'Official OpenAI API.' },
      { id: 'anthropic', label: 'Anthropic', model: 'claude-sonnet-4-20250514', default_model: 'claude-sonnet-4-20250514', env_key: 'ANTHROPIC_API_KEY', requires_key: true, configured: false, note: 'Native Anthropic Messages API (not OpenAI-compatible).' },
      { id: 'openrouter', label: 'OpenRouter', model: 'openai/gpt-4o-mini', default_model: 'openai/gpt-4o-mini', env_key: 'OPENROUTER_API_KEY', requires_key: true, configured: false, note: 'One key for hundreds of models.' },
      { id: 'deepseek', label: 'DeepSeek', model: 'deepseek-chat', default_model: 'deepseek-chat', env_key: 'DEEPSEEK_API_KEY', requires_key: true, configured: false, note: 'Low-cost reasoning and chat models.' },
      { id: 'groq', label: 'Groq', model: 'llama-3.3-70b-versatile', default_model: 'llama-3.3-70b-versatile', env_key: 'GROQ_API_KEY', requires_key: true, configured: false, note: 'Very fast inference.' },
      { id: 'ollama', label: 'Ollama (local)', model: 'qwen2.5:7b', default_model: 'qwen2.5:7b', env_key: null, requires_key: false, configured: true, note: 'Runs locally. Start Ollama before using this provider.' },
    ],
    vault: { available: true, count: 1, secrets: [{ name: 'OPENAI_API_KEY', value: 'set (****7Qk2)' }], error: '' },
    audit: { ok: true, entries: 24, message: '24 entries verified.' },
    sessions: [
      { id: sessionId, updated_at: nowIso(38), provider: 'openai', model: 'gpt-4o-mini', messages: messages.length, preview: 'Harden the public API edge' },
      { id: '20260308-101544-c7d0', updated_at: nowIso(9360), provider: 'anthropic', model: 'claude-sonnet-4-20250514', messages: 14, preview: 'Map the billing service and find the smallest safe refactor.' },
      { id: '20260306-173012-ef82', updated_at: nowIso(189600), provider: 'openai', model: 'gpt-4o-mini', messages: 9, preview: 'Write the incident review and extract the three follow-up fixes.' },
    ],
    session,
    running: false,
    secure_transport: true,
  };

  return {
    state,
    session,
    audit,
    approval: {
      id: 'demo-approval',
      tool: 'run_command',
      arguments: { command: 'npm run migrate -- --tenant atlas-prod' },
      risk: 'elevated',
      risk_title: 'Shell command',
      reasons: ['Changes operating-system or application state.', 'Runs with your desktop user permissions.'],
      summary: 'npm run migrate -- --tenant atlas-prod',
    },
  };
}

function demoAudit() {
  const events = [
    ['studio.opened', 'Mirsad Studio opened', 792],
    ['session.created', 'Session created · 20260309-142210-a91c', 760],
    ['settings.changed', 'Settings updated · openai', 758],
    ['credential.saved', 'Credential stored · openai', 756],
    ['approval.denied', 'run_command · denied', 700],
    ['tool.requested', 'run_command requested · high risk', 690],
    ['tool.finished', 'run_command finished · ok', 688],
    ['tool.requested', 'read_file requested · elevated risk', 680],
    ['tool.finished', 'read_file finished · ok', 678],
    ['run.started', 'Run started · session 20260309-142210-a91c', 540],
    ['tool.requested', 'list_files requested · elevated risk', 502],
    ['tool.finished', 'list_files finished · ok', 500],
    ['tool.requested', 'read_file requested · elevated risk', 482],
    ['tool.finished', 'read_file finished · ok', 480],
    ['approval.requested', 'read_file · requested', 476],
    ['approval.granted', 'read_file · granted', 474],
    ['tool.requested', 'write_file requested · high risk', 305],
    ['approval.requested', 'write_file · requested', 301],
    ['approval.granted', 'write_file · granted', 298],
    ['tool.finished', 'write_file finished · ok', 296],
    ['tool.requested', 'run_command requested · elevated risk', 74],
    ['approval.requested', 'run_command · requested', 70],
    ['approval.granted', 'run_command · granted', 62],
    ['tool.finished', 'run_command finished · ok', 39],
  ];
  return events.map(([event, summary, ago], index) => ({
    seq: index + 1,
    ts: nowIso(ago),
    event,
    summary,
    hash: Array.from(
      { length: 12 },
      () => '0123456789abcdef'[Math.floor(Math.random() * 16)]
    ).join(''),
  }));
}

async function demoInvoke(name) {
  const demo = App.demoData || demoData();
  App.demoData = demo;
  switch (name) {
    case 'bootstrap':
    case 'get_state':
      return { ok: true, state: clone(App.state) };
    case 'new_session':
      return {
        ok: true,
        session: {
          id: 'draft',
          title: 'Untitled operation',
          created_at: nowIso(),
          updated_at: nowIso(),
          provider: 'openai',
          model: 'gpt-4o-mini',
          workdir: App.state.workspace,
          plan: [],
          messages: [],
          message_count: 0,
        },
      };
    case 'load_session':
      return { ok: true, session: clone(App.session || demo.session) };
    case 'delete_session':
      return { ok: true };
    case 'send_message':
      demoEmit('user', { content: 'Draft a concise release note from the completed work.' });
      demoEmit('run', { state: 'running' });
      await sleep(180);
      demoEmit('step', { current: 1, total: 5 });
      demoEmit('typing', { active: true, label: 'Mirsad is thinking — step 1 of 5' });
      await sleep(850);
      demoEmit('plan', {
        steps: [
          'Collect the shipped changes and the evidence for each one.',
          'Draft a release note for engineers and operators.',
          'Remove claims that are not backed by the diff or tests.',
        ],
        note: 'Plan updated.',
      });
      demoEmit('typing', { active: false, label: '' });
      demoEmit('assistant', {
        content:
          'I’ll base the note on the work already on the record rather than inventing a summary. Here is the draft:\n\n## Release note — API abuse hardening\n\n- Added tenant-aware rate limiting to high-volume transfer and webhook paths. Existing response shapes are unchanged.\n- Added burst and sustained-traffic regression coverage.\n- The limiter is process-local; a shared store is required before horizontal scaling.\n\n**Verification:** the existing API suite passes with 3 tests, and the new burst case is green.',
      });
      demoEmit('run', { state: 'complete' });
      return { ok: true, session_id: demo.session.id };
    case 'cancel_run':
      demoEmit('run', { state: 'cancelled' });
      return undefined;
    case 'audit_entries':
      return {
        ok: true,
        entries: clone(demo.audit).reverse(),
        check: { ok: true, entries: demo.audit.length, message: `${demo.audit.length} entries verified.` },
      };
    case 'verify_audit':
      return { ok: true, entries: demo.audit.length, message: `${demo.audit.length} entries verified.`, broken_at: null };
    case 'save_settings':
      return { ok: true, state: clone(App.state) };
    case 'save_api_key':
      return { ok: true, state: clone(App.state) };
    case 'remove_api_key':
      return { ok: true, state: clone(App.state) };
    case 'choose_workspace':
      return { ok: true, path: 'C:\\Users\\Mirsad\\Work\\atlas-web' };
    default:
      return { ok: false, error: `Preview mode does not implement ${name}.` };
  }
}

function demoNotify(name, ...args) {
  if (name === 'resolve_approval') {
    demoEmit('approval.resolved', { id: args[0], approved: Boolean(args[1]), tool: 'run_command' });
  }
  if (name === 'cancel_run') {
    demoEmit('run', { state: 'cancelled' });
  }
}
