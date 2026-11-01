"""Warm fanart.tv cache + Navidrome->MusicBrainz maps (KY 2026-11-01).
Run on the Kodi box: python3 warm_fanart.py  (polite: fanart 0.5s, MusicBrainz 1.1s)."""
import json, sys, time, types, urllib.request, xml.etree.ElementTree as ET
ADDON = "/storage/.kodi/addons/plugin.kodi.navidrome"
S = {e.get('id'): (e.text or '') for e in ET.parse(
    "/storage/.kodi/userdata/addon_data/plugin.kodi.navidrome/settings.xml").getroot()}
x = types.ModuleType('xbmc'); x.log = lambda *a, **k: None
for n in ("LOGERROR", "LOGINFO", "LOGDEBUG", "LOGWARNING"): setattr(x, n, 0)
class _A:
    def __init__(s, *a): pass
    def getSetting(s, k): return S.get(k, '')
    def getSettingBool(s, k): return S.get(k, '') == 'true'
    def getAddonInfo(s, k): return '/tmp'
xa = types.ModuleType('xbmcaddon'); xa.Addon = _A
sys.modules.setdefault('xbmc', x); sys.modules.setdefault('xbmcaddon', xa)
sys.path.insert(0, ADDON)
from lib.navidrome_api import NavidromeAPI
from lib import fanart as F
api = NavidromeAPI(S['server_url'], S['username'], S['password'])
assert F._api_key(), "no fanart key"
m = F.load_map()
arts = api.get_artists() or []
print("artists", len(arts), flush=True)
withcd = []
for a in arts:
    mb = a.get('musicBrainzId')
    if not mb: continue
    F.remember_artist(a['id'], mb)
    before = F._load().get(mb, {}).get('ts')
    e = F.get_artist_entry(mb)
    if e.get('ts') != before: time.sleep(0.5)
    if e.get('cdart'): withcd.append(a)
print("artists with cdart", len(withcd), flush=True)
def rg_of(rel):
    if rel in m['release']: return m['release'][rel]
    rg = None
    try:
        req = urllib.request.Request(
            "https://musicbrainz.org/ws/2/release/%s?inc=release-groups&fmt=json" % rel,
            headers={"User-Agent": "KodiNavidrome-fanart/1.1 (home use)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rg = (json.load(r).get('release-group') or {}).get('id') or ""
    except urllib.error.HTTPError as ex:
        rg = "" if ex.code == 404 else None
    except Exception:
        rg = None
    time.sleep(1.1)
    if rg is not None:
        m['release'][rel] = rg
    return rg
hit = 0
for a in withcd:
    d = api.get_artist(a['id']) or {}
    for al in d.get('album', []):
        rel = al.get('musicBrainzId')
        if not rel: continue
        rg = rg_of(rel)
        if rg: m['album'][al['id']] = rg
        if rg and F.art_for(nav_album_id=al['id'], artist_mbid=a['musicBrainzId'], fetch=False).get('discart'): hit += 1
    F.save_map()
print("albums with discart", hit, flush=True)
