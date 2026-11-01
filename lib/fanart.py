"""fanart.tv artist backdrops for plugin.kodi.navidrome.

Added 2026-08-01. The addon previously set fanart to the square album cover, which
Kodi then stretched across a 16:9 screen. This fetches a real 1920x1080
artistbackground keyed on the MusicBrainz ID Navidrome already returns.

Key is READ from plugin.video.themoviedb.helper's settings so the secret lives in
exactly one place on the box and is never duplicated into this addon.

Every failure path returns None so the caller falls back to the cover — fanart is
cosmetic and must never break browsing.
"""
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET

_TMDBH = "/storage/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml"
_CACHE = "/storage/.kodi/userdata/addon_data/plugin.kodi.navidrome/fanart_cache.json"
_TTL = 30 * 24 * 3600          # re-check an artist monthly
_NEG_TTL = 7 * 24 * 3600       # re-check "no backdrop" weekly
_TIMEOUT = 8                   # never stall the UI

_key = None
_cache = None


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


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_CACHE, "r") as fh:
                _cache = json.load(fh)
        except Exception:
            _cache = {}
    return _cache


def _save():
    try:
        tmp = _CACHE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(_cache, fh)
        os.replace(tmp, _CACHE)
    except Exception:
        pass


def get_artist_background(mbid):
    """Return a 1920x1080 fanart.tv backdrop URL for this MusicBrainz artist id,
    or None (caller should fall back to the cover)."""
    if not mbid:
        return None
    key = _api_key()
    if not key:
        return None

    c = _load()
    now = time.time()
    hit = c.get(mbid)
    if hit:
        age = now - hit.get("ts", 0)
        if hit.get("url") and age < _TTL:
            return hit["url"]
        if not hit.get("url") and age < _NEG_TTL:
            return None

    url = None
    try:
        req = urllib.request.Request(
            "https://webservice.fanart.tv/v3/music/%s?api_key=%s" % (mbid, key),
            headers={"User-Agent": "KodiNavidrome-fanart/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            d = json.load(r)
        bgs = d.get("artistbackground") or []
        if bgs:
            # highest 'likes' first — the community's best pick
            try:
                bgs.sort(key=lambda b: int(b.get("likes") or 0), reverse=True)
            except Exception:
                pass
            url = bgs[0].get("url") or None
    except Exception:
        # network/quota/parse failure: cache nothing, just fall back this time
        return None

    c[mbid] = {"url": url, "ts": now}
    _save()
    return url
