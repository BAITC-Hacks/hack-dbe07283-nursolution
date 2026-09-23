import {element} from './ui.js';
const login = document.querySelector('#admin-login');
const workspace = document.querySelector('#admin-workspace');
const form = document.querySelector('#profile-form');
const fields = document.querySelector('#profile-fields');
const select = document.querySelector('#profile-select');
const status = document.querySelector('#admin-status');
const newButton = document.querySelector('#profile-new');
const reload = document.querySelector('#admin-reload');
const logout = document.querySelector('#admin-logout');
let token = '', records = [], selected = null, editable = false;

function message(text, error = false) { status.textContent = text; status.dataset.error = String(error); }
function busy(value) {
  fields.disabled = value || !editable;
  select.disabled = reload.disabled = logout.disabled = value;
  newButton.disabled = value || !editable;
}
async function api(path, method = 'GET', body) {
  const response = await fetch(`/admin/api${path}`, {
    method, headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(10000),
  });
  const result = await response.json();
  if (!response.ok) {
    const details = (result.error?.fields || []).map(item => `${item.field}: ${item.message}`).join(' ');
    throw new Error([result.error?.message || 'Не удалось выполнить запрос.', details].filter(Boolean).join(' '));
  }
  return result;
}
function show(record) {
  selected = record;
  const profile = record?.profile || {id:'', anon_name:'', city:'Алматы', categories:[], event_formats:[], languages:[], price_from_kzt:0, max_hours:null, busy_dates:[], description:''};
  for (const [key, value] of Object.entries(profile)) {
    const input = form.elements.namedItem(key);
    if (input) input.value = Array.isArray(value) ? value.join('|') : value ?? '';
  }
  form.elements.id.readOnly = Boolean(record);
  document.querySelector('#editor-title').textContent = record ? record.profile.anon_name : 'Новый профиль';
}
async function load(preferred) {
  const result = await api('/contractors');
  records = result.records; editable = result.editable;
  document.querySelector('#catalog-mode-note').hidden = editable;
  document.querySelector('#backend-label').textContent = `${result.backend === 'postgres' ? 'PostgreSQL · изменения сохраняются' : 'CSV · только чтение'} · ${records.length} профилей`;
  select.replaceChildren(...records.map(record => {
    const option = element('option', '', `${record.profile.anon_name} · ${record.profile.id}`);
    option.value = record.profile.id; return option;
  }));
  const record = records.find(item => item.profile.id === preferred) || records[0] || null;
  if (record) select.value = record.profile.id;
  show(record);
}
login.addEventListener('submit', async event => {
  event.preventDefault(); token = document.querySelector('#admin-token').value.trim();
  const button = login.querySelector('button'); button.disabled = true;
  try {
    await load(); login.hidden = true; workspace.hidden = false;
    document.querySelector('#admin-token').value = '';
    message(editable ? 'Каталог открыт.' : 'CSV доступен для просмотра. Для редактирования выберите PostgreSQL в .env.');
  } catch (error) { token = ''; message(error.message, true); }
  finally { button.disabled = false; busy(false); }
});
select.addEventListener('change', () => { show(records.find(item => item.profile.id === select.value)); message(''); });
newButton.addEventListener('click', () => { select.selectedIndex = -1; show(null); form.elements.id.focus(); message(''); });
reload.addEventListener('click', async () => { busy(true); try { await load(selected?.profile.id); message('Каталог перечитан.'); } catch (error) { message(error.message, true); } finally { busy(false); } });
logout.addEventListener('click', () => { token = ''; records = []; selected = null; select.replaceChildren(); form.reset(); workspace.hidden = true; login.hidden = false; message('Вы вышли из редактора.'); });
form.addEventListener('submit', async event => {
  event.preventDefault();
  const profile = Object.fromEntries(new FormData(form));
  for (const key of ['categories','event_formats','languages','busy_dates']) profile[key] = profile[key].split('|').map(value => value.trim()).filter(Boolean);
  profile.price_from_kzt = Number(profile.price_from_kzt);
  profile.max_hours = profile.max_hours === '' ? null : Number(profile.max_hours);
  const current = selected;
  busy(true);
  try {
    const result = current ? await api(`/contractors/${encodeURIComponent(profile.id)}`, 'PUT', {profile, revision:current.revision}) : await api('/contractors', 'POST', profile);
    // Keep returned revision even if refreshing the list subsequently fails.
    show(result);
    await load(profile.id);
    message('Сохранено. Новые запросы подбора уже используют эти данные.');
  } catch (error) { message(error.message, true); }
  finally { busy(false); }
});
