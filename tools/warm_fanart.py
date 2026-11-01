"""Warm the fanart.tv cache and the Navidrome -> MusicBrainz id map.

Run on the Kodi box (system Python, outside the addon process):

    python3 warm_fanart.py

Polite delays: fanart.tv 0.5s after a fetch, MusicBrainz 1.1s per release.
The fanart.tv key is read from TMDb Helper; this script never stores one.

Imports of the addon happen after the xbmc stubs are installed, because host
Python has no xbmc modules and lib/ imports them at module level.
"""
import json
import os
import sys
import time
import types
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TOOLS)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_USERDATA = '/storage/.kodi/userdata'
_ADDON_ID = 'plugin.kodi.navidrome'
_SETTINGS = _USERDATA + '/addon_data/' + _ADDON_ID + '/settings.xml'
_PROFILE = _USERDATA + '/addon_data/' + _ADDON_ID + '/'

# Bool settings whose addon default is true. A missing entry must not flip
# TLS verification off when this runs outside Kodi.
_DEFAULT_TRUE = {
    'verify_ssl',
    'enable_offline_cache',
    'enable_scrobbling',
    'enable_now_playing',
}


def _install_host_stubs():
    """Provide xbmc* for system Python. Real modules win when already imported."""
    if 'xbmc' in sys.modules:
        return

    settings = {}
    try:
        root = ET.parse(_SETTINGS).getroot()
        for el in root.findall('setting'):
            settings[el.get('id')] = (el.text or el.get('value') or '').strip()
    except Exception as exc:
        sys.stderr.write('could not read addon settings: %s\n' % exc)

    xbmc = types.ModuleType('xbmc')
    xbmc.log = lambda *args, **kwargs: None
    for name in ('LOGERROR', 'LOGINFO', 'LOGDEBUG', 'LOGWARNING'):
        setattr(xbmc, name, 0)

    class Addon:
        def __init__(self, addon_id=None):
            self.addon_id = addon_id or _ADDON_ID

        def getSetting(self, key):
            return settings.get(key, '')

        def getSettingBool(self, key):
            if key not in settings:
                return key in _DEFAULT_TRUE
            return settings.get(key) == 'true'

        def getAddonInfo(self, key):
            if key == 'profile':
                return _PROFILE
            return ''

    xbmcaddon = types.ModuleType('xbmcaddon')
    xbmcaddon.Addon = Addon

    def translate(path):
        prefix = 'special://profile'
        if path.startswith(prefix):
            return _USERDATA + path[len(prefix):]
        return path

    class File:
        def __init__(self, path, mode='r'):
            real = translate(path)
            self._fh = open(real, 'rb' if 'r' in mode else 'wb')

        def readBytes(self):
            return self._fh.read()

        def write(self, data):
            if isinstance(data, str):
                data = data.encode('utf-8')
            self._fh.write(bytes(data))
            return len(data)

        def close(self):
            self._fh.close()

    class Stat:
        def __init__(self, path):
            self._path = translate(path)

        def st_size(self):
            try:
                return os.path.getsize(self._path)
            except OSError:
                return 0

        def st_mtime(self):
            try:
                return os.path.getmtime(self._path)
            except OSError:
                return 0

    def exists(path):
        return os.path.exists(translate(path))

    def mkdirs(path):
        os.makedirs(translate(path), exist_ok=True)
        return True

    def delete(path):
        real = translate(path)
        try:
            os.remove(real)
            return True
        except OSError:
            return False

    def listdir(path):
        real = translate(path)
        try:
            names = os.listdir(real)
        except OSError:
            return [], []
        dirs, files = [], []
        for name in names:
            if os.path.isdir(os.path.join(real, name)):
                dirs.append(name)
            else:
                files.append(name)
        return dirs, files

    xbmcvfs = types.ModuleType('xbmcvfs')
    xbmcvfs.File = File
    xbmcvfs.Stat = Stat
    xbmcvfs.exists = exists
    xbmcvfs.mkdirs = mkdirs
    xbmcvfs.delete = delete
    xbmcvfs.listdir = listdir
    xbmcvfs.translatePath = translate
    xbmcvfs.makeLegalFilename = lambda text: text

    sys.modules['xbmc'] = xbmc
    sys.modules['xbmcaddon'] = xbmcaddon
    sys.modules['xbmcvfs'] = xbmcvfs


def _all_artists(api):
    """Every artist. 0.6.0 pages at 500, the old get_artists() returned them all."""
    artists = []
    offset = 0
    size = 500
    while True:
        page = api.get_artists(size=size, offset=offset) or []
        artists.extend(page)
        offset += len(page)
        total = api.last_total_count or 0
        if not page or len(page) < size or (total and offset >= total):
            break
    return artists


def _release_group(mapping, release_id):
    if release_id in mapping['release']:
        return mapping['release'][release_id]
    release_group = None
    try:
        req = urllib.request.Request(
            'https://musicbrainz.org/ws/2/release/%s?inc=release-groups&fmt=json' % release_id,
            headers={'User-Agent': 'KodiNavidrome-fanart/1.1 (home use)'},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.load(response)
            release_group = (payload.get('release-group') or {}).get('id') or ''
    except urllib.error.HTTPError as exc:
        release_group = '' if exc.code == 404 else None
    except Exception:
        release_group = None
    time.sleep(1.1)
    if release_group is not None:
        mapping['release'][release_id] = release_group
    return release_group


_install_host_stubs()

from lib.navidrome_api import NavidromeAPI  # noqa: E402
from lib import fanart as fanart_tv  # noqa: E402


def main():
    settings = {}
    root = ET.parse(_SETTINGS).getroot()
    for el in root.findall('setting'):
        settings[el.get('id')] = (el.text or el.get('value') or '').strip()

    api = NavidromeAPI(
        settings['server_url'], settings['username'], settings['password'])
    if not fanart_tv._api_key():
        sys.stderr.write('no fanart key in TMDb Helper settings\n')
        return 1

    mapping = fanart_tv.load_map()
    artists = _all_artists(api)
    print('artists', len(artists), flush=True)
    with_cdart = []
    for artist in artists:
        mbid = artist.get('musicBrainzId') or artist.get('mbzArtistId')
        if not mbid:
            continue
        fanart_tv.remember_artist(artist.get('id'), mbid)
        before = fanart_tv._load().get(mbid, {}).get('ts')
        entry = fanart_tv.get_artist_entry(mbid)
        if entry.get('ts') != before:
            time.sleep(0.5)
        if entry.get('cdart'):
            with_cdart.append(artist)
    print('artists with cdart', len(with_cdart), flush=True)

    hits = 0
    for artist in with_cdart:
        detail = api.get_artist(artist.get('id')) or {}
        artist_mbid = (
            artist.get('musicBrainzId') or artist.get('mbzArtistId')
            or detail.get('musicBrainzId') or detail.get('mbzArtistId')
        )
        for album in detail.get('album', []):
            release_id = album.get('musicBrainzId') or album.get('mbzAlbumId')
            if not release_id:
                continue
            release_group = _release_group(mapping, release_id)
            if release_group:
                mapping['album'][album.get('id')] = release_group
            if release_group and fanart_tv.art_for(
                nav_album_id=album.get('id'),
                artist_mbid=artist_mbid,
                fetch=False,
            ).get('discart'):
                hits += 1
        fanart_tv.save_map()
    print('albums with discart', hits, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
