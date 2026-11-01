"""Local browser report preparation. No submission route, storage or collection."""
import html
import json
from pathlib import Path
from .report import PROPERTIES, REPORT_SCHEMA, MAX_REPORT_BYTES

# Labels are presentation only. Machine values remain the exact report schema enums.
LABELS = {
    'app_version': 'Версия приложения', 'python_version': 'Версия Python',
    'platform': 'Платформа', 'component': 'Где возникла проблема', 'stage': 'На каком шаге',
    'reason': 'Что произошло', 'request_id': 'Код диагностики ответа',
    'http_status': 'Код ответа сервиса', 'installation': 'Состояние установки',
    'service': 'Состояние фоновой службы', 'pairing': 'Подключение устройства',
    'venv_available': 'Окружение Python готово',
}
VALUES = {
    'unknown': 'Не знаю', 'none': 'Ошибки нет', 'linux': 'Linux / SteamOS',
    'windows': 'Windows', 'macos': 'macOS', 'server': 'Сервис Game Assist',
    'web': 'Сайт', 'deck': 'Steam Deck', 'install': 'Установка', 'service': 'Фоновая служба',
    'pairing': 'Подключение устройства', 'authorization': 'Вход и разрешения',
    'request': 'Обращение к сервису', 'install_interrupted': 'Установка прервалась',
    'install_partial': 'Установка не завершена', 'unit_mismatch': 'Настройки службы отличаются',
    'working_directory_unavailable': 'Рабочая папка недоступна', 'venv_unavailable': 'Окружение Python недоступно',
    'service_failed': 'Служба завершилась с ошибкой', 'pairing_pending': 'Подключение ждёт подтверждения',
    'pairing_expired': 'Время подключения истекло', 'pairing_denied': 'Подключение отклонено',
    'consent_required': 'Нужно проверить разрешения', 'network_unavailable': 'Сеть недоступна',
    'upstream_timeout': 'Внешний сервис не ответил вовремя', 'upstream_unavailable': 'Внешний сервис недоступен',
    'origin_denied': 'Источник запроса не подтверждён', 'csrf_denied': 'Подтверждение действия устарело',
    'unauthenticated': 'Нужно войти снова', 'rate_limited': 'Слишком много запросов',
    'invalid_request': 'Не удалось проверить запрос', 'not_found': 'Запрошенное не найдено',
    'internal_error': 'Ошибка сервиса', 'request_cancelled': 'Запрос прерван',
    'missing': 'Отсутствует', 'interrupted': 'Прервано', 'partial': 'Не завершено',
    'present': 'Установлено', 'unsafe_or_unreadable': 'Не удалось безопасно проверить',
    'active': 'Работает', 'inactive': 'Остановлена', 'failed': 'Завершилась с ошибкой',
    'activating': 'Запускается', 'deactivating': 'Останавливается', 'unavailable': 'Недоступна',
    'pending': 'Ждёт подтверждения', 'expired': 'Время истекло', 'denied': 'Отклонено',
    'locally_valid_remote_not_checked': 'Настроено на устройстве, сервис не проверен',
    'true': 'Да', 'false': 'Нет',
}


def _control(key):
    spec = PROPERTIES[key]
    if 'enum' in spec or key == 'venv_available':
        values = spec.get('enum', ['unknown', 'true', 'false'])
        default = 'web' if key == 'component' else 'unknown'
        field = f'<select id="{key}" aria-describedby="{key}-error">' + ''.join(
            f'<option value="{html.escape(v, quote=True)}"' + (' selected' if v == default else '')
            + '>' + html.escape(VALUES[v]) + '</option>' for v in values) + '</select>'
    else:
        maximum = spec.get('maxLength', 3)
        placeholder = 'Например, 1.2.3' if key.endswith('_version') else 'Можно оставить пустым'
        keyboard = ' inputmode="numeric"' if key == 'http_status' else ''
        field = (f'<input id="{key}" aria-describedby="{key}-error" maxlength="{maximum}" value="" placeholder="{placeholder}"'
                 f'{keyboard} autocomplete="off" spellcheck="false">')
    return f'<div><label for="{key}">{LABELS[key]}</label>{field}<p id="{key}-error" class="small-text"></p></div>'


def preview_page():
    # Reuse the existing console shell/CSS without editing globally owned UI files.
    from remote_server.ui import page
    basic = ''.join(_control(key) for key in ('component', 'stage', 'reason'))
    device = ''.join(_control(key) for key in ('platform', 'installation', 'service', 'pairing', 'venv_available'))
    advanced = ''.join(_control(key) for key in ('app_version', 'python_version', 'http_status', 'request_id'))
    body = '''<div class="form-page onboarding diagnostics-preview">
<a class="plain-link back-link" href="/games">← Назад к играм</a>
<h1>Подготовить отчёт</h1>
<p class="intro">Выбери, что пошло не так. Если не уверен, оставь «Не знаю» — угадывать не нужно.</p>
<div class="connection"><h2>Только на твоём устройстве</h2>
<p>Отправка отчётов пока отключена. Здесь можно проверить отчёт и сохранить файл себе.
Ничего не отправляется в поддержку, и фонового сбора данных нет.</p>
<p class="small-text">Не вставляй пароли, коды подключения, логи, сохранения или пути к файлам.</p></div>
<noscript><p>Для подготовки отчёта нужен JavaScript. Данные не отправлены; можно вернуться к играм.</p></noscript>
<section class="form-stack" aria-labelledby="problem-title"><h2 id="problem-title">Что случилось</h2>
''' + basic + '''</section>
<details class="utility-section"><summary>Состояние устройства · необязательно</summary>
<p class="small-text">Укажи только то, что уже известно. Проверки автоматически не запускаются.</p>
''' + device + '''</details>
<details class="utility-section"><summary>Дополнительные сведения · необязательно</summary>
<p class="small-text">Версии и коды можно оставить пустыми. Код диагностики — только из ответа сервиса,
если он уже известен. Код подключения устройства здесь не нужен.</p>
''' + advanced + '''</details>
<div class="action-row chooser-actions"><button class="primary" type="button" id="prepare-report">Подготовить и просмотреть</button>
<button class="secondary" type="button" id="reset-report">Очистить поля</button>
<a class="button secondary" href="/games">Отмена</a></div>
<p id="report-error" role="alert"></p>
<section class="setup-section" aria-labelledby="preview-title"><h2 id="preview-title">Проверь перед сохранением</h2>
<p class="small-text">Ниже появятся все данные отчёта. Технические названия в файле нужны для диагностики.
Сохранение файла не отправляет его в поддержку.</p>
<pre id="report-preview" tabindex="0" aria-live="polite" aria-label="Содержимое отчёта"></pre>
<div class="action-row chooser-actions"><button class="secondary" type="button" id="download-report" disabled>Сохранить файл отчёта</button></div>
</section></div>'''
    return page('Диагностический отчёт', body, head='''<meta name="robots" content="noindex,nofollow">
<script src="/assets/diagnostics.js" defer></script>''').body.decode('utf-8')


def preview_script():
    # Only static schema constants; no session, host details or submitted values.
    return ('const GA_REPORT_SCHEMA = ' + json.dumps(REPORT_SCHEMA) + ';\n'
            + 'const GA_MAX_REPORT_BYTES = ' + str(MAX_REPORT_BYTES) + ';\n'
            + Path(__file__).with_name('preview.js').read_text(encoding='utf-8'))
