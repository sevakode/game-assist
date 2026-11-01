'use strict';

function validateReport(report) {
  const invalid = (field = null) => {
    const error = new Error('invalid_diagnostic_report');
    error.field = field;
    throw error;
  };
  if (!report || Array.isArray(report) || typeof report !== 'object') invalid();
  const properties = GA_REPORT_SCHEMA.properties;
  if (Object.keys(report).length !== Object.keys(properties).length) invalid();
  for (const [key, spec] of Object.entries(properties)) {
    if (!Object.hasOwn(report, key)) invalid(key);
    const value = report[key];
    const type = value === null ? 'null' : Number.isInteger(value) ? 'integer' : typeof value;
    if (![spec.type].flat().includes(type)) invalid(key);
    if (value === null) continue;
    if (Object.hasOwn(spec, 'const') && value !== spec.const) invalid(key);
    if (spec.enum && !spec.enum.includes(value)) invalid(key);
    if (typeof value === 'string' && (value.length > (spec.maxLength || 64) ||
        (spec.pattern && !(new RegExp(spec.pattern)).test(value)))) invalid(key);
    if (type === 'integer' && (value < (spec.minimum || 0) || value > (spec.maximum || 599))) invalid(key);
  }
  if (new TextEncoder().encode(JSON.stringify(report)).length > GA_MAX_REPORT_BYTES) invalid();
  return report;
}

if (typeof module !== 'undefined') module.exports = {validateReport};
if (typeof document !== 'undefined') {
  let prepared = null;
  const preview = document.getElementById('report-preview');
  const error = document.getElementById('report-error');
  const download = document.getElementById('download-report');
  const invalidate = () => {
    prepared = null;
    download.disabled = true;
    preview.textContent = '';
    error.textContent = '';
    for (const key of Object.keys(GA_REPORT_SCHEMA.properties)) {
      if (key === 'schema_version') continue;
      document.getElementById(key).removeAttribute('aria-invalid');
      document.getElementById(key + '-error').textContent = '';
    }
  };
  for (const element of document.querySelectorAll('input, select')) {
    element.addEventListener('input', invalidate);
    element.addEventListener('change', invalidate);
  }
  document.getElementById('reset-report').addEventListener('click', () => {
    invalidate();
    for (const key of Object.keys(GA_REPORT_SCHEMA.properties)) {
      if (key === 'schema_version') continue;
      document.getElementById(key).value = key === 'component' ? 'web' :
        (key.endsWith('_version') || key === 'request_id' || key === 'http_status') ? '' : 'unknown';
    }
    document.getElementById('component').focus();
  });
  document.getElementById('prepare-report').addEventListener('click', () => {
    invalidate();
    try {
      const report = {schema_version: 1};
      for (const key of Object.keys(GA_REPORT_SCHEMA.properties)) {
        if (key === 'schema_version') continue;
        const value = document.getElementById(key).value;
        report[key] = key === 'venv_available' ? (value === 'unknown' ? null : value === 'true') :
          key === 'http_status' ? (value === '' ? null : /^[1-5][0-9]{2}$/.test(value) ? Number(value) : value) :
          key === 'request_id' && value === '' ? null :
          key.endsWith('_version') && value === '' ? 'unknown' : value;
      }
      prepared = JSON.stringify(validateReport(report), null, 2);
      preview.textContent = prepared;
      download.disabled = false;
    } catch (failure) {
      prepared = null;
      error.textContent = 'Отчёт не готов. Проверь отмеченное поле — ничего не отправлено.';
      const key = failure.field;
      if (key && Object.hasOwn(GA_REPORT_SCHEMA.properties, key) && key !== 'schema_version') {
        const field = document.getElementById(key);
        const hint = key.endsWith('_version') ? 'Укажи три числа через точки, например 1.2.3, или оставь поле пустым.' :
          key === 'http_status' ? 'Укажи код ответа от 100 до 599 или оставь поле пустым.' :
          key === 'request_id' ? 'Нужен код диагностики из 32 строчных символов 0–9 и a–f. Если не знаешь его, оставь поле пустым.' :
          'Выбери значение из списка или «Не знаю».';
        document.getElementById(key + '-error').textContent = hint;
        field.setAttribute('aria-invalid', 'true');
        const details = field.closest('details');
        if (details) details.open = true;
        field.focus();
      }
    }
  });
  download.addEventListener('click', () => {
    if (prepared === null) return;
    const url = URL.createObjectURL(new Blob([prepared], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'game-assist-diagnostic.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  });
}
