'use strict';
// Only fresh checked responses may enter manual-copy UI; no storage or background exports.
(() => {
  const button = document.getElementById('ai-export-copy');
  const status = document.getElementById('ai-export-status');
  const manual = document.getElementById('ai-export-manual');
  const manualText = document.getElementById('ai-export-text');
  if (!button || !status) return;
  const original = {appid: button.dataset.appid, csrf: button.dataset.csrf, binding: button.dataset.binding};
  let blocked = false, busy = false, generation = 0, controller;
  const clearPreview = () => {
    if (manualText) manualText.value = '';
    if (manual) manual.hidden = true;
  };
  const invalidate = () => {
    blocked = true;
    generation++;
    if (controller) controller.abort();
    clearPreview();
    button.disabled = true;
    status.textContent = 'Обнови страницу перед новым копированием.';
  };
  window.addEventListener('pagehide', invalidate);
  window.addEventListener('pageshow', event => { if (event.persisted) invalidate(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) invalidate(); });
  if (typeof MutationObserver === 'function') new MutationObserver(invalidate).observe(button,
    {attributes: true, attributeFilter: ['data-appid', 'data-csrf', 'data-binding']});
  clearPreview();
  button.hidden = false;
  button.addEventListener('click', async () => {
    if (blocked || busy) return;
    if (Object.keys(original).some(key => button.dataset[key] !== original[key])) { invalidate(); return; }
    clearPreview();
    busy = true;
    button.disabled = true;
    button.textContent = 'Проверяем доступ…';
    status.textContent = '';
    const requestGeneration = ++generation;
    const started = performance.now();
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let payload;
    try {
      const response = await fetch('/account/ai-export', {
        method: 'POST', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store',
        headers: {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams(original), signal: controller.signal,
      });
      if (!response.ok || response.redirected || !response.headers.get('content-type')?.startsWith('application/json')) throw new Error('unavailable');
      payload = await response.json();
      if (blocked || document.hidden || requestGeneration !== generation) return;
      if (performance.now() - started > 10000) throw new Error('expired response');
      if (Object.keys(original).some(key => button.dataset[key] !== original[key])) { invalidate(); return; }
      if (payload.appid !== Number(original.appid) || typeof payload.text !== 'string' || payload.text.length > 5000 || !Number.isFinite(payload.checked_at)) throw new Error('invalid');
      try {
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') throw new Error('clipboard unavailable');
        await navigator.clipboard.writeText(payload.text);
      } catch (_) {
        // Recheck after an asynchronous clipboard denial; never reveal an old/context-changed response.
        if (blocked || document.hidden || requestGeneration !== generation) return;
        if (performance.now() - started > 10000) throw new Error('expired response');
        if (Object.keys(original).some(key => button.dataset[key] !== original[key])) { invalidate(); return; }
        if (!manual || !manualText) throw new Error('manual copy unavailable');
        manualText.value = payload.text;
        manual.hidden = false;
        manualText.focus();
        manualText.select();
        status.textContent = 'Автокопирование в этом браузере недоступно. Буфер не обновлён. Свежий проверенный снимок ниже: выдели текст и скопируй вручную. Время проверки указано в снимке.';
        return;
      }
      if (!blocked && requestGeneration === generation) {
        button.textContent = 'Сводка скопирована';
        status.textContent = 'Ручной снимок скопирован. В нём указано время проверки; это не подключение AI.';
      }
    } catch (_) {
      if (!blocked) status.textContent = 'Буфер не обновлён. Не удалось скопировать свежую сводку. Проверь вход и доступ, обнови страницу и повтори. Старый текст не используется.';
    } finally {
      payload = undefined;
      clearTimeout(timeout);
      busy = false;
      if (!blocked) {
        button.disabled = false;
        if (button.textContent !== 'Сводка скопирована') button.textContent = 'Скопировать сводку для AI';
      }
    }
  });
})();
