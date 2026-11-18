'use strict';
const $ = id => document.getElementById(id);
let selected = null;
let missions = [];
let liveEnabled = false;
let refreshing = false;

async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'action_impossible');
  return data;
}
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function stateLabel(state) {
  return ({ready: 'Préparation', running: 'En cours', awaiting_approval: 'À approuver', completed: 'Terminée', failed: 'Interrompue'})[state] || 'Inconnue';
}
function dateLabel(seconds) {
  return new Intl.DateTimeFormat('fr-FR', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(seconds * 1000));
}
function showLogin() { $('login').hidden = false; $('content').hidden = true; }
async function openSession() {
  try {
    const session = await api('/api/session');
    liveEnabled = session.live_enabled;
    $('live-option').hidden = !liveEnabled;
    $('login').hidden = true;
    $('content').hidden = false;
    await refresh();
  } catch (_) { showLogin(); }
}
async function refresh() {
  if (refreshing || $('content').hidden) return;
  refreshing = true;
  try {
    const data = await api('/api/missions');
    missions = data.missions;
    $('total-count').textContent = missions.length;
    $('pending-count').textContent = missions.filter(m => m.state === 'awaiting_approval').length;
    $('done-count').textContent = missions.filter(m => m.state === 'completed').length;
    $('calls-count').textContent = missions.reduce((n,m) => n + m.api_calls, 0);
    $('list-count').textContent = missions.length;
    const list = $('mission-list');
    list.replaceChildren();
    if (!missions.length) {
      const empty = element('div', 'detail-empty');
      empty.append(element('div', 'empty-icon', '✧'), element('h3', '', 'Votre journal est prêt'), element('p', '', 'Votre première mission apparaîtra ici.'));
      list.append(empty);
    }
    missions.forEach(m => {
      const row = element('button', 'mission-row' + (selected === m.id ? ' selected' : ''));
      row.type = 'button';
      const name = element('span', 'name', 'Analyse du dépôt témoin');
      name.append(element('small', '', dateLabel(m.created) + ' · ' + (m.mode === 'simulation' ? 'Simulation' : 'Réel')));
      row.append(element('span', 'mission-icon', '✦'), name, element('span', 'badge', stateLabel(m.state)));
      row.addEventListener('click', () => { selected = m.id; refresh(); });
      list.append(row);
    });
    if (selected) await renderDetail(selected);
  } catch (_) { $('detail-subtitle').textContent = 'Connexion interrompue. Nouvelle tentative…'; }
  finally { refreshing = false; }
}
async function renderDetail(id) {
  const m = await api('/api/missions/' + encodeURIComponent(id));
  $('detail-subtitle').textContent = stateLabel(m.state) + ' · ' + (m.mode === 'simulation' ? 'Simulation' : 'Réel') + ' · ' + m.api_calls + '/6 appels API';
  const detail = $('detail'); detail.className = ''; detail.replaceChildren();
  m.messages.forEach(message => {
    const box = element('div', 'message');
    const label = message.role === 'architect' ? (message.body.type === 'review' ? 'Architecte · évaluation' : 'Architecte · proposition') : 'Codex · réponse';
    box.append(element('small', '', label), element('p', '', message.body.summary));
    detail.append(box);
  });
  if (!m.messages.length) {
    const empty = element('div', 'detail-empty'); empty.append(element('p', '', 'DOBBY prépare la mission…')); detail.append(empty);
  }
  if (m.state === 'awaiting_approval') {
    const actions = element('div', 'detail-actions');
    actions.append(element('p', '', m.mode === 'simulation' ? 'Validez l’étape simulée pour poursuivre.' : 'Votre approbation autorise une exécution Codex en lecture seule.'));
    const button = element('button', 'primary', 'Approuver et poursuivre');
    button.addEventListener('click', async () => {
      if (!confirm('Approuver cette étape de la mission ?')) return;
      button.disabled = true;
      try { await api('/api/missions/' + encodeURIComponent(id) + '/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({approve:true})}); await refresh(); }
      catch (_) { alert('Cette étape ne peut pas être approuvée.'); button.disabled = false; }
    });
    actions.append(button); detail.append(actions);
  }
  if (m.state === 'failed') {
    const box = element('div', 'detail-actions'); box.append(element('p', 'error', 'Mission interrompue : ' + (m.error || 'erreur'))); detail.append(box);
  }
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); $('login-error').textContent = '';
  try { await api('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:$('password').value})}); $('password').value = ''; await openSession(); }
  catch (error) {
    $('password').value = '';
    if (error.message === 'setup_required') {
      $('login-form').hidden = true; $('setup-form').hidden = false;
      $('login-description').textContent = 'Choisissez un nouveau PIN personnel. Il est transmis uniquement à DOBBY en HTTPS et n’est jamais conservé en clair.';
      $('new-pin').focus();
    } else $('login-error').textContent = 'PIN invalide ou accès temporairement bloqué. Après 5 échecs, attendez 15 minutes.';
  }
});
$('setup-form').addEventListener('submit', async event => {
  event.preventDefault(); $('setup-error').textContent = '';
  const pin = $('new-pin').value, confirmation = $('confirm-pin').value;
  if (!/^[0-9]{6}$/.test(pin) || pin === '000000' || pin !== confirmation) { $('setup-error').textContent = 'Choisissez un nouveau PIN de six chiffres différent du code de première configuration, puis confirmez-le.'; return; }
  try {
    await api('/api/setup', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({bootstrap:'000000', pin, confirmation})});
    $('new-pin').value = ''; $('confirm-pin').value = ''; await openSession();
  } catch (_) { $('setup-error').textContent = 'Configuration refusée ou déjà effectuée. Après 5 essais incorrects, attendez 15 minutes.'; }
});
$('new-mission').addEventListener('click', () => $('create-dialog').showModal());
$('cancel-create').addEventListener('click', () => $('create-dialog').close());
$('mission-mode').addEventListener('change', () => { $('billing-label').hidden = $('mission-mode').value !== 'live'; });
$('create-form').addEventListener('submit', async event => {
  event.preventDefault(); $('create-error').textContent = '';
  const mode = $('mission-mode').value;
  if (mode === 'live' && (!liveEnabled || !$('billing-confirm').checked)) { $('create-error').textContent = 'La confirmation de facturation est nécessaire.'; return; }
  try {
    const result = await api('/api/missions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode, billing_confirmed: mode === 'live'})});
    selected = result.id; $('create-dialog').close(); $('billing-confirm').checked = false; await refresh();
  } catch (_) { $('create-error').textContent = 'Impossible de créer cette mission.'; }
});
openSession(); setInterval(refresh, 2500);
