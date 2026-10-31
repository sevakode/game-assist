"""Library projection after BOTH OAuth and account source consent checks.

No fetch, selection, grants or gameplay data. Cache source remains LibraryReader.
"""


def library_result(state, origin):
    result = {'status':'unknown', 'reason':'source_unavailable', 'games':[],
              'action':'review_source_and_refresh', 'url':origin+'/games#steam-library',
              'received_at':None, 'source':'steam_web_api_cache',
              'current_game':'unknown'}
    if not state['configured']:
        result.update(reason='operator_source_not_configured',action='choose_game_manually')
        result['url']=origin+'/games'
    elif not state['enabled']:
        result.update(reason='account_library_permission_required',action='review_library_permission')
    elif state['status']=='expired':
        result.update(reason='cache_expired',action='refresh_library_on_site')
    elif state['status']=='not_requested':
        result.update(reason='cache_not_requested',action='refresh_library_on_site')
    elif state['status']=='ok' and state['games']:
        result.update(status='available',reason='cached_library_available',
                      action='ask_user_which_game',received_at=state['received_at'],
                      games=[{'appid':game['appid'],'name':game['name']} for game in state['games']])
    # Empty/hidden/unavailable is unknown, never evidence of zero owned games.
    return result
