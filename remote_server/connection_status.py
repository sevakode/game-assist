"""Read-only agent diagnostics derived exclusively from the permitted projection.

Receipt age is not save age or device liveness. No account discovery, I/O, or
gameplay interpretation belongs in this adapter.
"""
import math


RECEIPT_REVIEW_AFTER_SECONDS = 86400


def receipt(received_at, now):
    if (type(received_at) not in (int, float) or not math.isfinite(received_at)
            or received_at < 0 or received_at > now):
        return {'received_at': None, 'received_age_seconds': None,
                'reason': 'receipt_time_unknown'}
    age = int(now - received_at)
    return {'received_at': received_at, 'received_age_seconds': age,
            'reason': ('receipt_older_than_review_threshold'
                       if age >= RECEIPT_REVIEW_AFTER_SECONDS else 'receipt_age_known')}


def connection_status(projection, origin, *, achievements_available, now):
    result = {
        'version': 1, 'connection': 'authenticated',
        'reasons': [], 'actions': [], 'games': [],
        'links': {name: origin + path for name, path in (
            ('games', '/games'), ('import', '/import'), ('setup', '/setup'),
            ('claude', '/connect/claude'))},
        'capabilities': {
            'steam_cloud': 'source_not_connected',
            'steam_achievements': ('available_requires_permission' if achievements_available
                                   else 'operator_source_not_configured'),
            'background_push': 'not_supported',
            'device_connection': 'unknown',
            'summary_coverage': 'four_raw_fields_only',
            'gameplay_semantics': 'unknown',
        },
        'receipt_review_after_seconds': RECEIPT_REVIEW_AFTER_SECONDS,
        'observation_time': 'unknown',
    }
    if not projection['games']:
        result['reasons'].append('no_authorized_games_visible')
        result['actions'].append('review_game_selection_and_permissions')
    for game in projection['games']:
        item = {'appid': game['appid'], 'reasons': [], 'actions': [], 'snapshots': {}}
        if not game['summary_supported']:
            item['reasons'].append('summary_decoder_unavailable')
        for kind in ('summary', 'metadata'):
            if game[kind] is None:
                continue
            source = game[kind + '_source']
            stamp = receipt(game[kind + '_received_at'], now)
            item['snapshots'][kind] = {
                'source': source if source in ('browser_manual', 'device') else 'unknown',
                **stamp,
            }
            if stamp['reason'] != 'receipt_age_known':
                item['actions'].append('review_snapshot_receipt')
        if game['summary'] is not None:
            item['reasons'].append('summary_snapshot_available')
            item['actions'].append('read_permitted_progress')
            if any(field['status'] != 'known'
                   for field in game['summary']['player_scalars'].values()):
                item['reasons'].append('summary_fields_unknown')
        elif game['metadata'] is not None:
            item['reasons'].append('metadata_is_not_game_progress')
        else:
            item['reasons'].append('no_visible_save_snapshot')
        if game['summary'] is None:
            # The projection intentionally does not expose missing grants or
            # pairing state. Never infer absent devices/permissions from silence.
            item['actions'].append('review_game_selection_and_permissions')
            if game['summary_supported']:
                item['actions'].append('review_manual_import')
            item['actions'].append('review_optional_companion')
        achievements = game.get('achievements')
        if achievements is not None:
            status = achievements['status']
            item['achievements'] = {
                'status': status if status in ('ok', 'expired', 'not_requested',
                    'not_configured', 'unavailable', 'private', 'rate_limited') else 'unknown',
                **receipt(achievements['received_at'], now),
            }
            if status != 'ok':
                item['actions'].append('review_achievement_source')
        item['actions'] = list(dict.fromkeys(item['actions']))
        result['games'].append(item)
    return result
