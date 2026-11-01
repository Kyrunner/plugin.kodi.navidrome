"""fanart.tv art for plugin.kodi.navidrome.

Artist backdrops, artist clearlogo (hdmusiclogo, then musiclogo) and per-album
CD discart, all from the same /v3/music/<artist mbid> response.

The fanart.tv key is read from plugin.video.themoviedb.helper's
``fanarttv_clientkey`` setting so the secret stays in that addon and is never
stored here.

fanart.tv keys album art by MusicBrainz release-group id. Navidrome exposes the
release id, so a release -> release-group map (navmap.json) is filled by
tools/warm_fanart.py. Browsing only reads that map; it never calls MusicBrainz.

Cache files live in the addon profile and go through xbmcvfs, same as the rest
of the 0.6.0 addon. Every failure path returns None or {} so callers fall back
to Navidrome cover art.
"""
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from lib import vfs

TMDB_HELPER_SETTINGS = (
    'special://profile/addon_data/plugin.video.themoviedb.helper/settings.xml'
)
_CACHE_NAME = 'fanart_cache.json'
_MAP_NAME = 'navmap.json'
_TTL = 30 * 24 * 3600
_NEG_TTL = 7 * 24 * 3600
_TIMEOUT = 8
_UA = 'KodiNavidrome-fanart/1.1'

_key = None
_cache = None
_map = None


def _cache_path():
    return vfs.profile_path(_CACHE_NAME)


def _map_path():
    return vfs.profile_path(_MAP_NAME)


def _api_key():
    """fanart.tv personal key from TMDb Helper's settings.xml. Never logged."""
    global _key
    if _key is not None:
        return _key
    _key = ''
    try:
        raw = vfs.read_bytes(TMDB_HELPER_SETTINGS)
        if not raw:
            return _key
        root = ET.fromstring(raw)
        for el in root.findall('setting'):
            if el.get('id') == 'fanarttv_clientkey':
                _key = (el.text or el.get('value') or '').strip()
                break
    except Exception:
        _key = ''
    return _key


def _read_json(path):
    try:
        data = vfs.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path, data):
    try:
        vfs.write_json(path, data)
    except Exception:
        return


def _load():
    global _cache
    if _cache is None:
        _cache = _read_json(_cache_path())
    return _cache


def _save():
    _write_json(_cache_path(), _cache or {})


def load_map():
    global _map
    if _map is None:
        _map = _read_json(_map_path())
        for key in ('artist', 'album', 'release'):
            if not isinstance(_map.get(key), dict):
                _map[key] = {}
    return _map


def save_map():
    if _map is not None:
        _write_json(_map_path(), _map)


def _best(lst):
    lst = list(lst or [])
    try:
        lst.sort(key=lambda item: int(item.get('likes') or 0), reverse=True)
    except Exception:
        pass
    return (lst[0].get('url') or None) if lst else None


def _parse(payload):
    logo = _best(payload.get('hdmusiclogo')) or _best(payload.get('musiclogo'))
    cdart = {}
    cover = {}
    for release_group, album in (payload.get('albums') or {}).items():
        if not isinstance(album, dict):
            continue
        disc = _best(album.get('cdart'))
        if disc:
            cdart[release_group] = disc
        image = _best(album.get('albumcover'))
        if image:
            cover[release_group] = image
    return {
        'url': _best(payload.get('artistbackground')),
        'logo': logo,
        'cdart': cdart,
        'albumcover': cover,
    }


def get_artist_entry(mbid, fetch=True):
    """Cached fanart.tv entry for an artist MBID. Empty when unknown.

    Entries saved by the older backdrop-only cache (no 'logo' key) are stale.
    """
    if not mbid:
        return {}
    cache = _load()
    now = time.time()
    hit = cache.get(mbid)
    if isinstance(hit, dict) and 'logo' in hit:
        age = now - hit.get('ts', 0)
        has_any = hit.get('url') or hit.get('logo') or hit.get('cdart')
        if (has_any and age < _TTL) or (not has_any and age < _NEG_TTL):
            return hit
    if not fetch:
        return hit or {}
    key = _api_key()
    if not key:
        return hit or {}
    try:
        req = urllib.request.Request(
            'https://webservice.fanart.tv/v3/music/%s?api_key=%s' % (mbid, key),
            headers={'User-Agent': _UA},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as response:
            payload = json.load(response)
        entry = _parse(payload if isinstance(payload, dict) else {})
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return hit or {}
        entry = _parse({})
    except Exception:
        return hit or {}
    entry['ts'] = now
    cache[mbid] = entry
    _save()
    return entry


def get_artist_background(mbid):
    """1920x1080 artistbackground URL, or None (caller uses the cover)."""
    return get_artist_entry(mbid).get('url')


def get_artist_logo(mbid):
    return get_artist_entry(mbid).get('logo')


def remember_artist(nav_id, mbid):
    if nav_id and mbid:
        mapping = load_map()
        if mapping['artist'].get(nav_id) != mbid:
            mapping['artist'][nav_id] = mbid
            save_map()


def remember_album(nav_album_id, release_mbid):
    """Link a Navidrome album id to its release-group via the release map."""
    if not nav_album_id or not release_mbid:
        return
    mapping = load_map()
    release_group = mapping['release'].get(release_mbid)
    if release_group and mapping['album'].get(nav_album_id) != release_group:
        mapping['album'][nav_album_id] = release_group
        save_map()


def art_for(nav_artist_id=None, artist_mbid=None, nav_album_id=None,
            release_mbid=None, fetch=True):
    """Return {'clearlogo': ..., 'discart': ...} for whatever is already known.

    Uses the cached id map. May fetch the artist from fanart.tv. Never raises.
    """
    out = {}
    try:
        mapping = load_map()
        mbid = artist_mbid or mapping['artist'].get(nav_artist_id or '')
        entry = get_artist_entry(mbid, fetch=fetch) if mbid else {}
        if entry.get('logo'):
            out['clearlogo'] = entry['logo']
        release_group = (
            mapping['release'].get(release_mbid or '')
            or mapping['album'].get(nav_album_id or '')
        )
        if release_group:
            disc = (entry.get('cdart') or {}).get(release_group)
            if not disc:
                # Compilation, or the track artist is not the album artist.
                for other in _load().values():
                    if not isinstance(other, dict):
                        continue
                    disc = (other.get('cdart') or {}).get(release_group)
                    if disc:
                        break
            if disc:
                out['discart'] = disc
    except Exception:
        return {}
    return out
