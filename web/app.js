'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const initial = {appid: 4231820, name: 'Castlevania Belmont’s Curse'};
  let token = '', selected = initial.appid, generation = 0, connected = false, busy = false;
  let games = new Map([[initial.appid, initial]]), scopes = new Set();
  const names = {achievements: 'Достижения', save_metadata: 'Метаданные сохранений', save_summary: 'Сводка ресурсов'};
  const states = {available: 'Есть данные', unknown: 'Нет наблюдений', not_permitted: 'Доступ выключен'};
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = !message; }
  function errorText(error) { return error.message || 'Не удалось выполнить запрос.'; }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: {...options.headers, Authorization: `Bearer ${token}`, ...(options.body ? {'Content-Type': 'application/json'} : {})}, cache: 'no-store', redirect: 'error'});
    let data; try { data = await response.json(); } catch { throw new Error(`Сервер вернул неожиданный ответ (HTTP ${response.status}).`); }
    if (!response.ok) { const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data); const error = new Error(`HTTP ${response.status}: ${detail}`); error.status = response.status; throw error; }
    return data;
  }
  function setBusy(value) {
    busy = value;
    $('refresh').disabled = !connected || value;
    $('export').disabled = !connected || value;
    $('delete').disabled = !connected || value || !$('scope-fields').dataset.registered;
    $('connect').disabled = value;
    $('disconnect').disabled = value;
    $('game-select').disabled = value;
    $('add-game').querySelector('button').disabled = !connected || value;
    $('save-permissions').disabled = !connected || value || !$('scope-fields').dataset.registered;
    $('scope-fields').disabled = !connected || value || !$('scope-fields').dataset.registered;
    $('assistance-fields').disabled = !connected || value || !$('assistance-fields').dataset.loaded;
    $('save-settings').disabled = !connected || value || !$('assistance-fields').dataset.loaded;
    $('neutral-reminders').disabled = !connected || value || !$('assistance-fields').dataset.loaded;
    if ($('steam-login')) $('steam-login').disabled = !connected || value;
    if ($('steam-unlink')) $('steam-unlink').disabled = !connected || value;
    if ($('steam-sync')) $('steam-sync').disabled = !connected || value || !scopes.has('achievements.read');
  }
  function renderGames() {
    $('game-select').replaceChildren();
    for (const game of games.values()) { const option = el('option', '', game.name); option.value = game.appid; $('game-select').append(option); }
    $('game-select').value = String(selected);
    $('game-title').textContent = games.get(selected)?.name || `Игра ${selected}`;
    $('game-appid').textContent = `APP ID ${selected}`;
  }
  function resetData() {
    delete $('assistance-fields').dataset.loaded;
    $('assistance-fields').disabled = true; $('save-settings').disabled = true;
    document.querySelector('[name="assistance"][value="standard"]').checked = true;
    $('settings-status').textContent = 'Режим не загружен.';
    $('neutral-reminders').checked = true; $('neutral-reminders').disabled = true;
    $('save-summary').replaceChildren(el('p', '', selected === 4231820 ? 'Разрешите локальную сводку отдельно. Только Belmont 1.1.3 и четыре исходных поля; без вывода о прохождении.' : 'Для этой игры структурный разбор ресурсов пока не поддерживается.'));
    $('progress-value').textContent = 'Неизвестен';
    $('progress-detail').textContent = 'Нужны проверенные данные';
    $('achievement-value').textContent = '—'; $('achievement-detail').textContent = 'Нет доступа к данным';
    $('save-value').textContent = '—'; $('save-detail').textContent = 'Метаданные не получены';
    $('achievements').className = 'list-empty'; $('achievements').textContent = 'Разрешите чтение достижений, чтобы увидеть доступные наблюдения.';
    $('saves').className = 'list-empty'; $('saves').textContent = 'Разрешите доступ к метаданным. Содержимое файлов не загружается.';
    $('progress-state').className = 'empty-state'; $('progress-state').replaceChildren(el('span', 'empty-icon', '⌖'), el('h3', '', 'Пока нет проверенной картины'), el('p', '', 'Метаданные файлов не показывают пройденных боссов, найденные предметы или исследованную карту.'));
  }
  function applyScopes(values) { scopes = new Set(values); for (const input of document.querySelectorAll('[name="scopes"]')) input.checked = scopes.has(input.value); }
  function renderProgress(data) {
    const target = $('progress-state'); target.className = ''; target.replaceChildren();
    for (const [key, value] of Object.entries(data.coverage || {})) { const row = el('div', 'coverage-row'); row.append(el('span', '', names[key] || key), el('span', '', states[value] || value)); target.append(row); }
    target.append(el('p', 'data-note', 'Прохождение игры: неизвестно. Структурный разбор отдельных полей не подтверждает найденные предметы, улучшения или пройденные события.'));
    $('progress-detail').textContent = 'Смысл прогресса не подтверждён';
  }
  function recordOf(data) { return data.observation || (data.achievements || Number.isInteger(data.file_count) ? {data, source: 'local_import'} : null); }
  function dateText(seconds) { const date = new Date(seconds * 1000); return Number.isFinite(date.getTime()) ? date.toLocaleString('ru-RU') : 'Время неизвестно'; }
  function sourceText(record) { return record.source === 'steam_web_api' ? 'Источник: Steam Web API. Доступность зависит от приватности профиля.' : 'Источник: локальный импорт. Не подтверждено независимо через Steam.'; }
  function renderAchievements(data) {
    const record = recordOf(data), target = $('achievements'); target.replaceChildren();
    if (!record) { target.textContent = 'Доступ разрешён, но наблюдений пока нет. Это не означает отсутствие достижений.'; $('achievement-detail').textContent = 'Наблюдений пока нет'; return; }
    const rows = (record.data?.achievements || []).filter(item => item.achieved === true);
    $('achievement-value').textContent = String(rows.length);
    $('achievement-detail').textContent = 'Уже получено в доступном снимке';
    target.append(el('p', 'data-note', sourceText(record)));
    if (!rows.length) target.append(el('p', '', 'В снимке нет полученных достижений. Будущие достижения скрыты; это не оценка прохождения.'));
    for (const item of rows) {
      const row = el('div', 'achievement-row unlocked'), body = el('div', 'row-main');
      body.append(el('strong', '', item.name || 'Полученное достижение'), el('div', 'row-detail', item.unlock_time ? dateText(item.unlock_time) : 'Дата не указана'));
      row.append(el('span', 'achievement-icon', '✦'), body, el('span', 'row-status', 'Получено'));
      target.append(row);
    }
  }
  function renderSaves(data) {
    const record = recordOf(data), target = $('saves'); target.replaceChildren();
    if (!record) { target.textContent = 'Доступ разрешён, но агент ещё не передал метаданные. Укажите ему конкретную папку сохранений.'; $('save-detail').textContent = 'Ожидание локального агента'; return; }
    const summary = record.data || {};
    const count = Number.isInteger(summary.file_count) ? summary.file_count : null;
    $('save-value').textContent = count === null ? '—' : String(count); $('save-detail').textContent = 'Файлов в последнем снимке';
    target.append(el('p', 'data-note', 'Имена файлов и хеши скрыты: они могут раскрыть будущие события. Прогресс по метаданным не определяется.'));
    if (count === null) { target.append(el('p', '', 'Безопасная сводка недоступна. Обновите локальный сервер.')); return; }
    const row = el('div', 'save-row'), body = el('div', 'row-main');
    body.append(el('strong', '', `Файлов: ${count}`));
    if (Number.isFinite(summary.total_bytes)) body.append(el('div', 'row-detail', `Общий размер: ${summary.total_bytes.toLocaleString('ru-RU')} байт`));
    if (summary.last_modified_ns) body.append(el('div', 'row-detail', `Последнее изменение: ${dateText(Number(summary.last_modified_ns) / 1e9)}`));
    row.append(el('span', 'section-icon', '▱'), body); target.append(row);
  }
  function renderSaveSummary(response) {
    const target = $('save-summary'); target.replaceChildren();
    const summary = response.observation?.data;
    if (selected !== 4231820) { target.append(el('p', '', 'Разбор ресурсов для этой игры не поддерживается.')); return; }
    if (!summary) { target.append(el('p', '', 'Доступ разрешён, но локальная сводка ещё не получена. Нужен локально разобранный снимок Belmont версии 1.1.3. Отсутствие данных не равно нулю.')); return; }
    if (summary.format_version !== '1.1.3') { target.append(el('p', '', 'Версия сводки не поддерживается. Значения не показаны.')); return; }
    target.append(el('p', 'data-note', 'Источник: локально переданная сводка парсера. Независимая проверка на реальном сохранении не подтверждена.'));
    const fields = [
      ['healthUpgradeFragmentCount', 'Счётчик фрагментов здоровья'],
      ['manaUpgradeFragmentCount', 'Счётчик фрагментов маны'],
      ['currentHealth', 'Текущее здоровье — не максимум'],
      ['currentMana', 'Текущая мана — не максимум'],
    ];
    for (const [key, label] of fields) {
      const field = summary.player_scalars?.[key];
      const known = field?.status === 'known' && typeof field.value === 'number' && Number.isFinite(field.value) && field.value >= 0;
      const value = known ? field.value.toLocaleString('ru-RU') : (field?.status === 'missing' ? 'Поле отсутствует' : 'Неизвестно');
      const row = el('div', 'coverage-row'); row.append(el('span', '', label), el('span', '', value)); target.append(row);
    }
    target.append(el('p', 'data-note', 'Исходные значения из сохранения, без игровой интерпретации. Не установлено, хранят счётчики общее число фрагментов или остаток. Это не число завершённых улучшений.'));
    target.append(el('p', 'data-note', 'Покрытие: только 4 поля. Предметы, их получение, локации и максимумы ресурсов не определены. Полный процент прохождения не рассчитывается.'));
  }
  function renderSettings(data) {
    const mode = ['minimal', 'standard', 'guided'].includes(data.assistance) ? data.assistance : 'standard';
    document.querySelector(`[name="assistance"][value="${mode}"]`).checked = true;
    $('neutral-reminders').checked = data.neutral_reminders !== false;
    $('assistance-fields').dataset.loaded = 'yes';
    $('settings-status').textContent = 'Режим сохранён. Спойлеры запрещены во всех режимах.';
  }
  async function loadGame() {
    const revision = ++generation, id = selected; resetData(); applyScopes([]); delete $('scope-fields').dataset.registered;
    $('permission-status').textContent = 'Загрузка разрешений…';
    let permissions;
    try { permissions = await api(`/v1/games/${id}/permissions`); }
    catch (error) { if (revision !== generation) return; if (error.status === 404) { $('permission-status').textContent = 'Профиль ещё не зарегистрирован. Добавьте его в разделе «Моя игра».'; $('appid').value = id; $('game-name').value = games.get(id)?.name || ''; $('add-game').closest('details').open = true; return; } throw error; }
    if (revision !== generation) return;
    $('scope-fields').dataset.registered = 'yes'; applyScopes(permissions.scopes || []);
    const available = new Set(permissions.available_scopes || ['library.read', 'achievements.read', 'saves.metadata', 'recommendations']);
    for (const input of document.querySelectorAll('[name="scopes"]')) { input.disabled = !available.has(input.value) || (input.value === 'saves.summary' && selected !== 4231820); input.closest('label').title = input.disabled ? 'Недоступно для этой игры или версии сервера' : ''; } $('permission-status').textContent = 'Загружены сохранённые настройки.';
    const requests = [['settings', renderSettings]];
    if (scopes.has('achievements.read') || scopes.has('saves.metadata') || scopes.has('saves.summary')) requests.push(['progress', renderProgress]);
    if (scopes.has('achievements.read')) requests.push(['achievements', renderAchievements]);
    if (scopes.has('saves.metadata')) requests.push(['save-status', renderSaves]);
    if (scopes.has('saves.summary') && selected === 4231820) requests.push(['save-summary', renderSaveSummary]);
    const results = await Promise.allSettled(requests.map(async ([path, render]) => { const data = await api(`/v1/games/${id}/${path}`); if (revision === generation) render(data); }));
    if (revision !== generation) return;
    const errors = results.filter(r => r.status === 'rejected').map(r => errorText(r.reason)); if (errors.length) notice(errors.join(' · '), true);
  }
  async function action(fn) { if (busy) return; setBusy(true); notice(''); try { await fn(); } catch (error) { notice(errorText(error), true); } finally { setBusy(false); } }
  $('connect-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
    token = $('token').value.trim();
    try { const data = await api('/v1/games'); connected = true; for (const game of data.games || []) games.set(game.appid, game); renderGames(); $('token').value = ''; $('token').hidden = true; $('connect').hidden = true; $('disconnect').hidden = false; $('connection-badge').classList.remove('muted'); $('connection-badge').replaceChildren(el('i'), document.createTextNode('Локальный сервер подключён')); await loadGame(); if (typeof loadSteam === 'function') await loadSteam(); }
    catch (error) { if (!connected) token = ''; throw error; }
  }); });
  $('disconnect').addEventListener('click', () => {
    ++generation; connected = false; token = ''; scopes.clear(); games = new Map([[initial.appid, initial]]); selected = initial.appid; renderGames(); resetData(); applyScopes([]); delete $('scope-fields').dataset.registered;
    $('token').hidden = false; $('connect').hidden = false; $('disconnect').hidden = true; $('connection-badge').classList.add('muted'); $('connection-badge').replaceChildren(el('i'), document.createTextNode('Не подключён')); $('permission-status').textContent = 'Подключитесь, чтобы загрузить настройки.'; if ($('steam-status')) { $('steam-status').textContent = 'Подключите локальный сервер'; $('steam-game-status').textContent = 'Steam не подключён'; $('steam-login').hidden = false; $('steam-unlink').hidden = true; $('steam-sync').hidden = true; $('steam-config').textContent = 'Вход через официальный сайт Steam. Пароль не передаётся Game Assist.'; } setBusy(false); notice('Соединение закрыто. Токен и данные удалены из памяти интерфейса.'); $('token').focus();
  });
  $('refresh').addEventListener('click', () => action(async () => { const data = await api('/v1/games'); for (const game of data.games || []) games.set(game.appid, game); renderGames(); await loadGame(); if (typeof loadSteam === 'function') await loadSteam(); }));
  $('game-select').addEventListener('change', () => action(async () => { selected = Number($('game-select').value); renderGames(); await loadGame(); }));
  $('game-preset').addEventListener('change', () => {
    const preset = $('game-preset').value;
    if (!preset) return;
    const titles = {'4231820':'Castlevania Belmont’s Curse', '1245620':'ELDEN RING', '292030':'The Witcher 3: Wild Hunt'};
    $('appid').value = preset; $('game-name').value = titles[preset];
  });
  $('add-game').addEventListener('submit', event => { event.preventDefault(); action(async () => { const game = {appid: Number($('appid').value), name: $('game-name').value.trim()}; if (!game.name || !Number.isSafeInteger(game.appid) || game.appid < 1) throw new Error('Введите корректные App ID и название.'); const result = await api('/v1/games', {method:'POST', body: JSON.stringify(game)}); games.set(game.appid, {...game, ...result}); selected = game.appid; renderGames(); await loadGame(); notice('Профиль сохранён. Разрешения изменяются отдельно.'); $('add-game').closest('details').open = false; }); });
  $('permissions-form').addEventListener('change', () => { $('permission-status').textContent = 'Есть изменения. Они начнут действовать после сохранения.'; });
  $('permissions-form').addEventListener('submit', event => { event.preventDefault(); action(async () => { const values = [...document.querySelectorAll('[name="scopes"]:checked')].map(input => input.value); await api(`/v1/games/${selected}/permissions`, {method:'PUT', body:JSON.stringify({scopes:values})}); await loadGame(); notice('Разрешения сохранены только для выбранной игры.'); }); });
  $('settings-form').addEventListener('change', () => { $('settings-status').textContent = 'Изменение ещё не сохранено. Защита от спойлеров остаётся включённой.'; });
  $('settings-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
    const assistance = document.querySelector('[name="assistance"]:checked').value;
    const result = await api(`/v1/games/${selected}/settings`, {method:'PUT', body:JSON.stringify({assistance, neutral_reminders:$('neutral-reminders').checked})});
    renderSettings(result); notice('Уровень помощи сохранён для этой игры. Все режимы — без спойлеров.');
  }); });
  $('export').addEventListener('click', () => action(async () => { const data = await api('/v1/export'); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'})); const link = el('a'); link.href = url; link.download = `game-assist-${new Date().toISOString().slice(0,10)}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); notice('Экспорт подготовлен: только разрешённые данные.'); }));
  $('delete').addEventListener('click', () => $('delete-dialog').showModal());
  $('delete-dialog').addEventListener('close', () => { if ($('delete-dialog').returnValue !== 'delete') return; action(async () => { await api(`/v1/games/${selected}/permissions`, {method:'PUT', body:JSON.stringify({scopes:[]})}); await api(`/v1/games/${selected}/data`, {method:'DELETE'}); await loadGame(); notice('Локальные данные удалены, разрешения отозваны. Файлы игры не изменялись.'); }); });
  async function loadSteam() {
    const status = await api('/v1/steam/status');
    $('steam-status').textContent = status.linked ? `Steam ID: ${status.steamid}` : 'Аккаунт не связан';
    $('steam-game-status').textContent = status.linked ? 'Steam связан' : 'Steam не подключён';
    $('steam-config').textContent = status.api_configured ? 'Ключ API настроен на сервере; доступ к профилю проверяется при синхронизации.' : 'Для достижений нужен SGC_STEAM_API_KEY на сервере. Вход Steam доступен без него.';
    $('steam-login').hidden = status.linked; $('steam-unlink').hidden = !status.linked;
    $('steam-sync').hidden = !status.linked;
  }
  $('steam-login').addEventListener('click', () => action(async () => {
    const data = await api('/v1/steam/login', {method:'POST'});
    const url = new URL(data.authorize_url);
    if (url.protocol !== 'https:' || url.hostname !== 'steamcommunity.com') throw new Error('Сервер вернул неожиданный адрес входа Steam.');
    window.location.assign(url.href);
  }));
  $('steam-unlink').addEventListener('click', () => action(async () => { await api('/v1/steam/unlink', {method:'POST'}); await loadSteam(); await loadGame(); notice('Steam отвязан. Импортированные из Steam наблюдения удалены.'); }));
  $('steam-sync').addEventListener('click', () => action(async () => {
    const result = await api(`/v1/games/${selected}/steam-sync`, {method:'POST'});
    await loadGame();
    notice(result.status === 'ok' ? 'Синхронизация завершена. Показаны только уже полученные достижения.' : (result.message || result.status), result.status !== 'ok');
  }));
  const callbackState = new URLSearchParams(window.location.search).get('steam');
  if (callbackState) { notice(callbackState === 'linked' ? 'Steam связан. Повторно введите локальный токен: он не сохранялся при переходе.' : 'Вход Steam отменён или не завершён. Подключитесь к серверу и попробуйте снова.', callbackState !== 'linked'); history.replaceState(null, '', window.location.pathname + window.location.hash); }
  renderGames(); setBusy(false);
})();
