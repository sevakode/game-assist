"""Optional metadata-only owned-library reader; no credentials or API calls at import.

Steam's response may omit identity: absent echoes are request-bound, not an
independent identity proof. Empty/hidden responses are unknown, never zero-owned.
"""
import json
import os
import re
import time
import httpx
from .achievements import _private_request, _install_private_transport_logging, _unique, _reject_constant

ENDPOINT='https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/'
MAX_RESULT=256*1024

def result(status,games=None):
    return {'status':status,'games':games or [],'source':'steam_web_api'}

class LibraryReader:
    def __init__(self,api_key=None,transport=None,monotonic=time.monotonic):
        self._api_key=os.environ.get('SGC_STEAM_API_KEY','') if api_key is None else api_key
        self._transport=transport;self._monotonic=monotonic
        _install_private_transport_logging()
    @property
    def configured(self):return isinstance(self._api_key,str) and bool(self._api_key.strip())
    def get_games(self,steamid):
        if not self.configured:return result('not_configured')
        if not isinstance(steamid,str) or not re.fullmatch(r'[0-9]{17}',steamid):return result('unavailable')
        token=_private_request.set(True)
        try:
            started=self._monotonic()
            with httpx.Client(transport=self._transport,timeout=httpx.Timeout(8.0,connect=3.0),follow_redirects=False,trust_env=False) as client:
                with client.stream('GET',ENDPOINT,params={'input_json':json.dumps({'steamid':steamid,'include_appinfo':True,'include_played_free_games':True},separators=(',',':'))},headers={'x-webapi-key':self._api_key}) as response:
                    if response.status_code!=200:return result('unavailable')
                    body=bytearray()
                    for chunk in response.iter_bytes():
                        if len(body)+len(chunk)>1048576 or self._monotonic()-started>12:return result('unavailable')
                        body.extend(chunk)
                    if self._monotonic()-started>12:return result('unavailable')
            data=json.loads(body,object_pairs_hook=_unique,parse_constant=_reject_constant)
            response=data.get('response') if isinstance(data,dict) else None
            if not isinstance(response,dict):return result('unavailable')
            for identity in ('steamid','steamID'):
                if identity in response and response[identity]!=steamid:return result('unavailable')
            rows=response.get('games');count=response.get('game_count')
            # No documented reliable private-vs-empty discriminator: fail unknown.
            if not isinstance(rows,list) or not 0<len(rows)<=1000 or type(count) is not int or count!=len(rows):return result('unavailable')
            games=[];seen=set()
            for row in rows:
                if not isinstance(row,dict):return result('unavailable')
                appid,name=row.get('appid'),row.get('name')
                if type(appid) is not int or not 0<appid<=2147483647 or appid in seen or not isinstance(name,str) or not 0<len(name)<=120 or not name.isprintable():return result('unavailable')
                seen.add(appid);games.append({'appid':appid,'name':name})
            output=result('ok',games)
            if len(json.dumps(output,ensure_ascii=False,separators=(',',':')).encode())>MAX_RESULT:return result('unavailable')
            return output
        except (httpx.HTTPError,OSError,ValueError,TypeError,UnicodeError,RecursionError,OverflowError):return result('unavailable')
        finally:_private_request.reset(token)
