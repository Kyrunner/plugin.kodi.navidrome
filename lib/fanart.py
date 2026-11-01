"""fanart.tv art for plugin.kodi.navidrome.

Added 2026-08-01 (artist backdrops). Extended 2026-11-01: artist clearlogo
(hdmusiclogo, fallback musiclogo) and per-album disc art (cdart) + album cover,
all from the same /v3/music/<artist mbid> response.

Key is READ from plugin.video.themoviedb.helper's settings so the secret lives in
exactly one place on the box and is never duplicated into this addon.

fanart.tv keys album art by MusicBrainz RELEASE-GROUP id, but Navidrome only
exposes the RELEASE id, so a release -> release-group map (navmap.json) is filled
by the warm script (tools/warm_fanart.py, MusicBrainz at 1 req/s). The UI path
only READS that map; it never calls MusicBrainz, so browsing never stalls.

Every failure path returns None/{} so callers fall back - art is cosmetic and
must never break browsing.
"""
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

_TMDBH = "/storage/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml"
_DATA = "/storage/.kodi/userdata/addon_data/plugin.kodi.navidrome"
_CACHE = _DATA + "/fanart_cache.json"
_MAP = _DATA + "/navmap.json"
_TTL = 30 * 24 * 3600          # re-check an artist monthly
_NEG_TTL = 7 * 24 * 3600       # re-check "no art at all" weekly
_TIMEOUT = 8                   # never stall the UI
_UA = "KodiNavidrome-fanart/1.1"

_key = None
_cache = None
_map = None


def _api_key():
    global _key
    if _key is None:
        _key = ""
        try:
            for el in ET.parse(_TMDBH).getroot().findall("setting"):
                if el.get("id") == "fanarttv_clientkey":
                    _key = (el.text or "").strip()
        except Exception:
            _key = ""
    return _key


def _read(path):
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def _load():
    global _cache
    if _cache is None:
        _cache = _read(_CACHE)
    return _cache


def _save():
    _write(_CACHE, _cache)


def load_map():
    global _map
    if _map is None:
        _map = _read(_MAP)
        for k in ("artist", "album", "release"):
            _map.setdefault(k, {})
    return _map


def save_map():
    if _map is not None:
        _write(_MAP, _map)


def _best(lst):
    lst = list(lst or [])
    try:
        lst.sort(key=lambda b: int(b.get("likes") or 0), reverse=True)
    except Exception:
        pass
    return (lst[0].get("url") or None) if lst else None


def _parse(d):
    logo = _best(d.get("hdmusiclogo")) or _best(d.get("musiclogo"))
    cdart, cover = {}, {}
    for rg, a in (d.get("albums") or {}).items():
        u = _best(a.get("cdart"))
        if u:
            cdart[rg] = u
        u = _best(a.get("albumcover"))
        if u:
            cover[rg] = u
    return {"url": _best(d.get("artistbackground")), "logo": logo,
            "cdart": cdart, "albumcover": cover}


def get_artist_entry(mbid, fetch=True):
    """Cached fanart.tv entry for an artist MBID (dict, maybe empty).
    Entries from the old format (no 'logo' key) count as stale."""
    if not mbid:
        return {}
    c = _load()
    now = time.time()
    hit = c.get(mbid)
    if hit and "logo" in hit:
        age = now - hit.get("ts", 0)
        has_any = hit.get("url") or hit.get("logo") or hit.get("cdart")
        if (has_any and age < _TTL) or (not has_any and age < _NEG_TTL):
            return hit
    if not fetch:
        return hit or {}
    key = _api_key()
    if not key:
        return hit or {}
    try:
        req = urllib.request.Request(
            "https://webservice.fanart.tv/v3/music/%s?api_key=%s" % (mbid, key),
            headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            d = json.load(r)
        entry = _parse(d)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return hit or {}
        entry = _parse({})          # fanart.tv has nothing for this artist
    except Exception:
        return hit or {}            # network/quota: keep whatever we had
    entry["ts"] = now
    c[mbid] = entry
    _save()
    return entry


def get_artist_background(mbid):
    return get_artist_entry(mbid).get("url")


def get_artist_logo(mbid):
    return get_artist_entry(mbid).get("logo")


def remember_artist(nav_id, mbid):
    if nav_id and mbid:
        m = load_map()
        if m["artist"].get(nav_id) != mbid:
            m["artist"][nav_id] = mbid
            save_map()


def remember_album(nav_album_id, release_mbid):
    """Link a Navidrome album id to its release-group via the release map."""
    if not nav_album_id or not release_mbid:
        return
    m = load_map()
    rg = m["release"].get(release_mbid)
    if rg and m["album"].get(nav_album_id) != rg:
        m["album"][nav_album_id] = rg
        save_map()


def art_for(nav_artist_id=None, artist_mbid=None, nav_album_id=None,
            release_mbid=None, fetch=True):
    """Return {'clearlogo':..., 'discart':...} for whatever is known.
    Uses only cached maps for ids; may fetch the artist from fanart.tv."""
    out = {}
    try:
        m = load_map()
        mbid = artist_mbid or m["artist"].get(nav_artist_id or "")
        e = get_artist_entry(mbid, fetch=fetch) if mbid else {}
        if e.get("logo"):
            out["clearlogo"] = e["logo"]
        rg = (m["release"].get(release_mbid or "") or
              m["album"].get(nav_album_id or ""))
        if rg:
            u = e.get("cdart", {}).get(rg)
            if not u:   # compilation / track artist != album artist
                for ent in _load().values():
                    u = (ent.get("cdart") or {}).get(rg)
                    if u:
                        break
            if u:
                out["discart"] = u
    except Exception:
        pass
    return out
