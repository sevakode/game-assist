'use strict';
// Enhancement only: navigation and selectable text work without JavaScript.
for (const button of document.querySelectorAll('[data-copy]')) {
  button.hidden = false;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    const field = document.getElementById(button.dataset.copy);
    const status = document.getElementById(button.dataset.copy + '-status');
    button.disabled = true;
    button.textContent = 'Копирование…';
    status.textContent = '';
    try {
      await navigator.clipboard.writeText(field.value);
      button.textContent = 'Скопировано';
      status.textContent = 'Текст скопирован. Подключение этим не подтверждается.';
    } catch (_) {
      button.textContent = 'Копировать ещё раз';
      field.focus();
      field.select();
      status.textContent = 'Текст выделен. Скопируй его вручную через меню или Ctrl/Cmd+C.';
    } finally {
      button.disabled = false;
    }
  });
}
