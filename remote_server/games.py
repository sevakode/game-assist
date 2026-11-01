"""Explicit first-three catalog, not the user's owned Steam library."""
CURRENT_GAME_IDS = (4231820, 1245620, 292030)
CATALOG_REVISION = 'initial-three-v1'
GAMES = {
    4231820: {'name': 'Castlevania: Belmont’s Curse', 'summary_supported': True},
    1245620: {'name': 'Elden Ring', 'summary_supported': False},
    292030: {'name': 'The Witcher 3: Wild Hunt', 'summary_supported': False},
}

# Identity-only discovery list, verified against each official Steam store URL on
# 2026-10-31. No ownership, ranking, release, decoder or game-content assertions.
# Adding an entry here must never register/select/grant it for an account.
DISCOVERY_TITLES = {
    **{appid: value['name'] for appid,value in GAMES.items()},
    1086940: "Baldur's Gate 3",
    1091500: 'Cyberpunk 2077',
    1174180: 'Red Dead Redemption 2',
    489830: 'The Elder Scrolls V: Skyrim Special Edition',
    377160: 'Fallout 4',
    413150: 'Stardew Valley',
    105600: 'Terraria',
    367520: 'Hollow Knight',
    1145360: 'Hades',
    264710: 'Subnautica',
    1771300: 'Kingdom Come: Deliverance II',
    2246340: 'Monster Hunter Wilds',
    814380: 'Sekiro: Shadows Die Twice - GOTY Edition',
    374320: 'DARK SOULS III',
}


def discovery_catalog(achievements_available=False):
    """Fresh public identity DTOs; no permissions or personal library inferred."""
    return [{'appid':appid,'name':name,'priority':appid in CURRENT_GAME_IDS,
             'summary_supported':appid==4231820,'metadata_supported':True,
             'cloud_available':False,'achievements_available':bool(achievements_available),
             'store_url':f'https://store.steampowered.com/app/{appid}/'}
            for appid,name in DISCOVERY_TITLES.items()]


def public_game_identity(appid):
    """Display identity only; never use account labels or infer ownership."""
    name = DISCOVERY_TITLES.get(appid)
    return {'name': name, 'name_source': 'public_registry' if name else 'unknown'}
