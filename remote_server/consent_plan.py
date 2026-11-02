"""Short-lived, owner/session-bound consent reviews; no I/O or new credentials."""
import hashlib
import json
import secrets
import time
from starlette.exceptions import HTTPException
from .games import public_game_identity

CATEGORY_SCOPES = {'metadata':'saves.metadata', 'summary':'saves.summary',
                   'achievements':'achievements.read'}


def invalidate_plans(db, owner):
    # Existing pending limit bounds storage; targeted predicate avoids other owners.
    for row in db.execute("SELECT id,data FROM oauth_pending WHERE json_extract(data,'$._review_owner')=?", (owner,)).fetchall():
        data = json.loads(row['data'])
        data.pop('_review_plan', None)
        data.pop('_review_owner', None)
        db.execute('UPDATE oauth_pending SET data=? WHERE id=?',
                   (json.dumps(data,separators=(',',':')),row['id']))


def require_session(db, session, now):
    if not db.execute('SELECT 1 FROM sessions WHERE hash=? AND owner=? AND csrf=? AND expires>?',
            (session['hash'],session['owner'],session['csrf'],now)).fetchone():
        raise HTTPException(401,'Sign in again before confirming')


def pending_row(db, request_id, now):
    key = hashlib.sha256(request_id.encode()).hexdigest()
    row = db.execute('SELECT data FROM oauth_pending WHERE id=? AND expires>?',(key,now)).fetchone()
    if not row:
        raise HTTPException(400,'Expired authorization request')
    return key, json.loads(row['data'])


def snapshot(db, owner, scopes, *, achievements_available, library_available):
    selected = [dict(row) for row in db.execute(
        'SELECT appid,selected_at FROM game_selections WHERE owner=? ORDER BY appid',(owner,))]
    grants = [dict(row) for row in db.execute(
        'SELECT appid,scope FROM grants WHERE owner=? ORDER BY appid,scope',(owner,))]
    library = db.execute('SELECT consent_id FROM library_cache WHERE owner=?',(owner,)).fetchone()
    games=[]
    for row in selected:
        appid=row['appid']; categories=['metadata']
        if appid==4231820: categories.append('summary')
        if achievements_available: categories.append('achievements')
        games.append({'appid':appid,'trusted_name_or_null':public_game_identity(appid)['name'],
                      'categories':categories})
    public={'games':games,'oauth_scopes':list(scopes),
            'library_source_change':bool('library.read' in scopes and library_available and not library),
            'zero_games':not games}
    baseline={'selected':selected,'grants':grants,
              'library_epoch':library['consent_id'] if library else None,
              'achievements_available':bool(achievements_available),'library_available':bool(library_available)}
    return public, baseline


def prepare_plan(store, provider, session, request_id):
    with store.db() as db:
        now=time.time(); require_session(db,session,now)
        key,data=pending_row(db,request_id,provider.clock())
        public,baseline=snapshot(db,session['owner'],data['scopes'],
            achievements_available=store.achievements_available, library_available=store.library_available)
        public['plan_id']=secrets.token_urlsafe(32)
        data['_review_owner']=session['owner']
        data['_review_plan']={'session_hash':session['hash'],'public':public,'baseline':baseline}
        db.execute('UPDATE oauth_pending SET data=? WHERE id=?',
                   (json.dumps(data,separators=(',',':')),key))
    return public


def approve_plan(store, provider, session, request_id, plan_id, *, achievement_rows_global,
                 achievement_rows_per_owner, library_rows_global):
    with store.db() as db:
        require_session(db,session,time.time())
        _,data=pending_row(db,request_id,provider.clock())
        saved=data.get('_review_plan')
        if (not saved or data.get('_review_owner')!=session['owner']
                or saved['session_hash']!=session['hash']
                or not secrets.compare_digest(saved['public']['plan_id'],plan_id)):
            raise HTTPException(409,'Consent review changed; review again')
        public,baseline=snapshot(db,session['owner'],data['scopes'],
            achievements_available=store.achievements_available, library_available=store.library_available)
        if saved['baseline']!=baseline or {k:v for k,v in saved['public'].items() if k!='plan_id'}!=public:
            raise HTTPException(409,'Consent review changed; review again')
        owner=session['owner']
        # All reservations, grants and code issuance share one rollback boundary.
        for game in public['games']:
            appid=game['appid']
            for category in game['categories']:
                db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(owner,appid,CATEGORY_SCOPES[category]))
            if 'achievements' in game['categories']:
                if not db.execute('SELECT 1 FROM achievement_cache WHERE owner=? AND appid=?',(owner,appid)).fetchone():
                    if (db.execute('SELECT count(*) FROM achievement_cache').fetchone()[0]>=achievement_rows_global
                            or db.execute('SELECT count(*) FROM achievement_cache WHERE owner=?',(owner,)).fetchone()[0]>=achievement_rows_per_owner):
                        raise HTTPException(429,'Achievement cache capacity reached')
                    db.execute('INSERT INTO achievement_cache(owner,appid,consent_id) VALUES(?,?,?)',
                               (owner,appid,secrets.token_urlsafe(32)))
        if public['library_source_change']:
            if db.execute('SELECT count(*) FROM library_cache').fetchone()[0]>=library_rows_global:
                raise HTTPException(429,'Library cache capacity reached')
            db.execute('INSERT INTO library_cache(owner,consent_id) VALUES(?,?)',(owner,secrets.token_urlsafe(32)))
        target=provider.approve(request_id,owner,granted_scopes=public['oauth_scopes'],connection=db)
        invalidate_plans(db,owner)
        return target
