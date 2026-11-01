"""Explicit, session-bound manual snapshot export. No readers, writes, or full projection."""
import hashlib
import hmac
import json
import math
import secrets
import time
from datetime import datetime, timezone

from starlette.exceptions import HTTPException
from server.app import SaveSummary
from .games import DISCOVERY_TITLES

APPID = 4231820
TOKEN_TTL = 300
SCALARS = (
    ('currentHealth', 'Текущее здоровье'),
    ('currentMana', 'Текущая мана'),
    ('healthUpgradeFragmentCount', 'Сырой счётчик фрагментов здоровья'),
    ('manaUpgradeFragmentCount', 'Сырой счётчик фрагментов маны'),
)


def stamp(value, now):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= now:
        return 'неизвестно'
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, OverflowError, OSError):
        return 'неизвестно'


class ManualAIExport:
    def __init__(self, store):
        self.store = store
        # Restart invalidates outstanding pages; no persistent secret/table required.
        self._key = secrets.token_bytes(32)

    def _state(self, db, session, appid, now):
        live = db.execute('SELECT * FROM sessions WHERE hash=? AND expires>?', (session['hash'], now)).fetchone()
        if not live or not live['owner'] or live['owner'] != session['owner'] or not secrets.compare_digest(live['csrf'], session['csrf']):
            raise HTTPException(401, 'Refresh sign-in')
        owner = live['owner']
        selected = sorted(row['appid'] for row in db.execute('SELECT appid FROM game_selections WHERE owner=?', (owner,)))
        if appid not in selected:
            raise HTTPException(409, 'Selection changed')
        scopes = sorted(row['scope'] for row in db.execute('SELECT scope FROM grants WHERE owner=? AND appid=?', (owner, appid)))
        if not ({'achievements.read', 'saves.summary'} & set(scopes)):
            raise HTTPException(403, 'No export permission')
        achievement = db.execute('SELECT consent_id,payload,status,received_at,expires FROM achievement_cache WHERE owner=? AND appid=?', (owner, appid)).fetchone() if 'achievements.read' in scopes else None
        summary = db.execute("SELECT payload,observed,source FROM observations_v2 WHERE owner=? AND appid=? AND kind='save_summary'", (owner, appid)).fetchone() if appid == APPID and 'saves.summary' in scopes else None
        achievement = dict(achievement) if achievement else None
        summary = dict(summary) if summary else None
        # Bind selected set and grant/cache epochs, including revoke/regrant and changed snapshots.
        revision = hashlib.sha256(json.dumps([selected, scopes, achievement, summary], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return scopes, achievement, summary, revision

    def _sign(self, session, appid, issued, revision):
        value = f"{session['hash']}:{appid}:{issued}:{revision}"
        return hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()

    def issue(self, session, appid):
        if type(appid) is not int:
            return None
        try:
            with self.store.db() as db:
                now = time.time()
                *_, revision = self._state(db, session, appid, now)
            issued = int(now)
            return f'{issued}.{self._sign(session, appid, issued, revision)}'
        except HTTPException:
            return None

    def construct(self, session, appid, binding):
        try:
            issued_text, signature = binding.split('.')
            issued = int(issued_text)
            if str(issued) != issued_text or len(signature) != 64 or any(c not in '0123456789abcdef' for c in signature):
                raise ValueError
        except (AttributeError, ValueError):
            raise HTTPException(409, 'Refresh export page') from None
        with self.store.db() as db:
            now = time.time()
            if not 0 <= now - issued <= TOKEN_TTL:
                raise HTTPException(409, 'Refresh export page')
            scopes, achievement, summary, revision = self._state(db, session, appid, now)
            if not secrets.compare_digest(signature, self._sign(session, appid, issued, revision)):
                raise HTTPException(409, 'Export context changed')
            lines = [
                'Ручной снимок Game Assist для AI — не подключение и не данные в реальном времени.',
                f'Игра: {DISCOVERY_TITLES.get(appid, f"Steam AppID {appid}")} (AppID {appid}).',
                f'Разрешения проверены сервером: {stamp(now, now)}.',
            ]
            has_data = False
            if 'achievements.read' in scopes:
                if not self.store.achievements_available:
                    raise HTTPException(409, 'Achievement source unavailable')
                if achievement and achievement['status'] == 'expired':
                    raise HTTPException(409, 'Achievement cache expired')
                if achievement and achievement['status'] == 'ok':
                    expires = achievement['expires']
                    if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= now:
                        raise HTTPException(409, 'Achievement cache expired')
                    try:
                        items = json.loads(achievement['payload'])
                        if not isinstance(items, list) or len(items) > 10000 or any(not isinstance(item, dict) or not isinstance(item.get('apiname'), str) or set(item) - {'apiname', 'name', 'unlock_time'} for item in items):
                            raise ValueError
                    except (ValueError, TypeError):
                        raise HTTPException(409, 'Invalid achievement cache') from None
                    lines.append(f"Открытые достижения: {len(items)} в доступном кэшированном ответе; статус: получен; источник: Steam Web API; получен сервером: {stamp(achievement['received_at'], now)}.")
                    lines.append('Нулевой счётчик означает только пустой возвращённый список; это не процент прохождения.')
                    has_data = True
                else:
                    status = 'ещё не запрошен' if not achievement or achievement['status'] == 'not_requested' else 'недоступен'
                    lines.append(f'Открытые достижения: число неизвестно; статус: {status}; источник: Steam Web API; время получения: неизвестно.')
            else:
                lines.append('Открытые достижения: чтение не разрешено; число неизвестно.')
            if summary:
                try:
                    parsed = SaveSummary.model_validate_json(summary['payload'])
                except ValueError:
                    raise HTTPException(409, 'Invalid save snapshot') from None
                source = {'browser_manual': 'ручной импорт', 'device': 'компаньон'}.get(summary['source'], 'неизвестно')
                lines.append(f"Сводка Belmont 1.1.3: исторический снимок; источник: {source}; получен сервером: {stamp(summary['observed'], now)}. Время самого сейва неизвестно.")
                for key, label in SCALARS:
                    scalar = getattr(parsed.player_scalars, key)
                    value = str(scalar.value) if scalar.status == 'known' else 'неизвестно'
                    lines.append(f'{label}: {value}.')
                has_data = True
            else:
                lines.append('Сводка сейва: разрешённого снимка нет; значения неизвестны.')
            if not has_data:
                raise HTTPException(409, 'No permitted cached snapshot')
            lines.extend([
                'Текущее местоположение, инвентарь, боссы, максимальные HP/мана и процент прохождения: неизвестно.',
                'Достижения не доказывают текущий инвентарь; сырые счётчики не обозначают готовые улучшения.',
                'AI: не добавляй спойлеры и не угадывай состояние. Спроси мою уже известную цель. Этот текст не даёт доступа к аккаунту.',
                'Отзыв доступа не удаляет уже скопированный текст.',
            ])
            return {'text': '\n'.join(lines), 'appid': appid, 'checked_at': now}
