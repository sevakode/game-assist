"""Frozen 88c3fa OAuth-only renderer for explicit legacy protocol tests.

Never use this fixture to assert the production consolidated UI contract.
"""
from functools import wraps
from unittest.mock import patch
from remote_server.ui import esc, hidden

def legacy_consent_body(csrf, req, client_label, scopes=('progress.read',)):
    descriptions = {
        'progress.read': 'Только разрешённые тобой сводки, метаданные и сохранённые открытые достижения.',
        'library.read': 'Список игр из библиотеки Steam: AppID и названия. Только пока отдельно включено чтение библиотеки на сайте. Без времени игры и иконок. Это не выбирает игры и не разрешает чтение их сейвов или достижений.',
    }
    permissions = ''.join(f'<li><strong>{esc(scope)}</strong>: {descriptions[scope]}</li>' for scope in scopes if scope != 'library.read')
    if 'library.read' in scopes:
        permissions += f'<li><label><input type="checkbox" name="library_read" value="yes"> Дополнительно разрешить library.read — библиотеку игр</label><p>{descriptions["library.read"]}</p><p>Необязательно: без отметки помощник получит только progress.read.</p></li>'
    return f'''<div class="form-page"><a class="back-link" href="/">К играм</a><h1>Доступ помощника</h1><p class="intro">Разрешить этому клиенту читать перечисленные данные?</p><div class="client-label"><strong>Клиент и адрес возврата</strong><p>{esc(client_label)}</p></div><form method="post" action="/oauth/consent">{hidden('csrf',csrf)}{hidden('request',req)}<ul class="permission-list">{permissions}<li>Без сырых сохранений и Steam ID.</li><li>Переданные факты покинут Game Assist.</li></ul><p class="small-text">Доступ можно отозвать в настройках на главной.</p><p class="small-text">После нажатия браузер должен вернуться в AI-клиент. Если переход не произошёл, проверь подключение там и начни новую попытку из клиента. Повторное нажатие здесь не завершит подключение.</p><div class="action-row"><button class="primary">Разрешить чтение данных</button><a class="plain-link" href="/">Не подключать</a></div></form></div>'''


def legacy_consent(test):
    @wraps(test)
    def run(*args, **kwargs):
        with patch('remote_server.app.ui.consent_body', new=legacy_consent_body):
            return test(*args, **kwargs)
    return run
