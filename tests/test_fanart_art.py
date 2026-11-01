"""Clearlogo / discart list-item behaviour, with Kodi and fanart.tv mocked.

Run from the repo root:

    python3 -m unittest tests.test_fanart_art -v
"""
import io
import json
import os
import sys
import types
import unittest
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Installed before any addon import. default.py reads sys.argv at import time.
sys.argv = ['plugin://plugin.kodi.navidrome/', '1', '']

ARTIST_MBID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
RELEASE_MBID = '11111111-2222-3333-4444-555555555555'
RELEASE_GROUP = '99999999-8888-7777-6666-555555555555'
LOGO = 'https://assets.fanart.tv/logo-hd.png'
CDART = 'https://assets.fanart.tv/cd.png'
BACKGROUND = 'https://assets.fanart.tv/bg-high.jpg'
FAKE_KEY = 'unit-test-key'


class _Files:
    def __init__(self):
        self.data = {}
        self.dirs = set()

    def reset_cache(self):
        keep = {}
        for path, blob in self.data.items():
            if path.endswith('themoviedb.helper/settings.xml'):
                keep[path] = blob
        self.data = keep
        self.dirs = set()


FILES = _Files()


def _install_kodi_modules():
    xbmc = types.ModuleType('xbmc')
    xbmc.LOGDEBUG = 0
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGERROR = 3
    xbmc.log = lambda *args, **kwargs: None
    xbmc.PLAYLIST_MUSIC = 0

    class PlayList:
        def __init__(self, playlist_id):
            self.playlist_id = playlist_id
            self.urls = []

        def clear(self):
            self.urls = []

        def add(self, url, listitem):
            self.urls.append(url)

    class Player:
        played = []

        def play(self, playlist):
            Player.played.append(playlist)

    xbmc.PlayList = PlayList
    xbmc.Player = Player

    xbmcaddon = types.ModuleType('xbmcaddon')

    class Addon:
        def __init__(self, addon_id=None):
            self.addon_id = addon_id or 'plugin.kodi.navidrome'

        def getAddonInfo(self, key):
            if key == 'profile':
                return 'special://profile/addon_data/%s/' % self.addon_id
            return ''

        def getSetting(self, key):
            return {
                'server_url': 'https://music.example',
                'username': 'user',
                'password': 'secret',
                'items_per_page': '50',
                'api_timeout': '10',
            }.get(key, '')

        def getSettingBool(self, key):
            return key == 'verify_ssl'

    xbmcaddon.Addon = Addon

    xbmcgui = types.ModuleType('xbmcgui')

    class MusicInfoTag:
        def __init__(self):
            self.values = {}

        def setTitle(self, value):
            self.values['title'] = value

        def setArtist(self, value):
            self.values['artist'] = value

        def setAlbum(self, value):
            self.values['album'] = value

        def setDuration(self, value):
            self.values['duration'] = value

        def setTrack(self, value):
            self.values['track'] = value

        def setDisc(self, value):
            self.values['disc'] = value

        def setYear(self, value):
            self.values['year'] = value

        def setMediaType(self, value):
            self.values['mediatype'] = value

        def setUserRating(self, value):
            self.values['rating'] = value

    class ListItem:
        def __init__(self, label='', path=''):
            self.label = label
            self.path = path
            self.art = {}
            self.context = []
            self.properties = {}
            self.tag = MusicInfoTag()

        def getMusicInfoTag(self):
            return self.tag

        def setArt(self, art):
            self.art.update(art or {})

        def addContextMenuItems(self, items):
            self.context.extend(items or [])

        def setMimeType(self, mime):
            self.mime = mime

        def setContentLookup(self, enabled):
            self.content_lookup = enabled

        def setProperty(self, key, value):
            self.properties[key] = value

    class Dialog:
        def notification(self, *args, **kwargs):
            return None

        def input(self, *args, **kwargs):
            return ''

        def select(self, *args, **kwargs):
            return -1

        def yesno(self, *args, **kwargs):
            return False

    xbmcgui.ListItem = ListItem
    xbmcgui.Dialog = Dialog
    xbmcgui.NOTIFICATION_INFO = 1
    xbmcgui.NOTIFICATION_WARNING = 2
    xbmcgui.NOTIFICATION_ERROR = 3

    xbmcplugin = types.ModuleType('xbmcplugin')
    xbmcplugin.items = []
    xbmcplugin.SORT_METHOD_UNSORTED = 0
    xbmcplugin.SORT_METHOD_ARTIST = 1
    xbmcplugin.SORT_METHOD_ALBUM = 2
    xbmcplugin.SORT_METHOD_TRACKNUM = 3

    def addDirectoryItem(handle, url, listitem, isFolder=False):
        xbmcplugin.items.append(listitem)
        return True

    def addSortMethod(handle, method):
        return None

    def setContent(handle, content):
        return None

    def endOfDirectory(handle, cacheToDisc=True):
        return None

    def setResolvedUrl(handle, success, listitem):
        return None

    xbmcplugin.addDirectoryItem = addDirectoryItem
    xbmcplugin.addSortMethod = addSortMethod
    xbmcplugin.setContent = setContent
    xbmcplugin.endOfDirectory = endOfDirectory
    xbmcplugin.setResolvedUrl = setResolvedUrl

    xbmcvfs = types.ModuleType('xbmcvfs')

    class File:
        def __init__(self, path, mode='r'):
            self.path = path
            self.mode = mode

        def readBytes(self):
            blob = FILES.data.get(self.path, b'')
            if isinstance(blob, str):
                blob = blob.encode('utf-8')
            return blob

        def write(self, data):
            if isinstance(data, str):
                data = data.encode('utf-8')
            FILES.data[self.path] = bytes(data)
            return len(FILES.data[self.path])

        def close(self):
            return True

    def exists(path):
        stripped = path.rstrip('/')
        return path in FILES.data or stripped in FILES.dirs

    def mkdirs(path):
        FILES.dirs.add(path.rstrip('/'))
        return True

    def delete(path):
        FILES.data.pop(path, None)
        return True

    def translatePath(path):
        return path

    def makeLegalFilename(text):
        return text

    xbmcvfs.File = File
    xbmcvfs.exists = exists
    xbmcvfs.mkdirs = mkdirs
    xbmcvfs.delete = delete
    xbmcvfs.translatePath = translatePath
    xbmcvfs.makeLegalFilename = makeLegalFilename
    xbmcvfs.listdir = lambda path: ([], [])

    class Stat:
        def __init__(self, path):
            blob = FILES.data.get(path, b'')
            self._size = len(blob)

        def st_size(self):
            return self._size

        def st_mtime(self):
            return 0

    xbmcvfs.Stat = Stat

    sys.modules['xbmc'] = xbmc
    sys.modules['xbmcaddon'] = xbmcaddon
    sys.modules['xbmcgui'] = xbmcgui
    sys.modules['xbmcplugin'] = xbmcplugin
    sys.modules['xbmcvfs'] = xbmcvfs
    return xbmc, xbmcplugin


XBMC, XBMCPLUGIN = _install_kodi_modules()

import urllib.request  # noqa: E402

from lib import fanart as fanart_tv  # noqa: E402
from lib import vfs  # noqa: E402
import default  # noqa: E402


def _settings_xml(key):
    if key:
        body = '<setting id="fanarttv_clientkey">%s</setting>' % key
    else:
        body = '<setting id="something_else">nope</setting>'
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<settings version="2">%s</settings>' % body).encode('utf-8')


def _fanart_payload():
    return {
        'artistbackground': [
            {'url': 'https://assets.fanart.tv/bg-low.jpg', 'likes': '1'},
            {'url': BACKGROUND, 'likes': '9'},
        ],
        'hdmusiclogo': [{'url': LOGO, 'likes': '4'}],
        'musiclogo': [{'url': 'https://assets.fanart.tv/logo-sd.png', 'likes': '1'}],
        'albums': {
            RELEASE_GROUP: {
                'cdart': [{'url': CDART, 'likes': '2'}],
            },
        },
    }


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeAPI:
    def __init__(self):
        self.last_total_count = 1
        self.similar = []
        self.enable_transcoding = False
        self.transcode_format = 'mp3'

    def ping(self):
        return True

    def get_artists(self, size=500, offset=0):
        return [{
            'id': 'ar1',
            'name': 'Radiohead',
            'coverArt': 'ar1',
            'musicBrainzId': ARTIST_MBID,
        }]

    def get_cover_art_url(self, cover_art_id, size=1000):
        return 'https://navidrome.example/cover/%s' % cover_art_id

    def get_similar_songs(self, song_id, count=50):
        return list(self.similar)


ALBUM = {
    'id': 'al1',
    'name': 'OK Computer',
    'artist': 'Radiohead',
    'artistId': 'ar1',
    'coverArt': 'al1',
    'year': 1997,
    'musicBrainzId': RELEASE_MBID,
}

SONG = {
    'id': 'tr1',
    'title': 'Paranoid Android',
    'artist': 'Radiohead',
    'album': 'OK Computer',
    'artistId': 'ar1',
    'albumId': 'al1',
    'coverArt': 'al1',
    'duration': 383,
    'track': 2,
    'discNumber': 2,
    'suffix': 'flac',
    'year': 1997,
}


class FanartArtTests(unittest.TestCase):
    def setUp(self):
        XBMCPLUGIN.items = []
        XBMC.Player.played = []
        FILES.reset_cache()
        FILES.data[fanart_tv.TMDB_HELPER_SETTINGS] = _settings_xml(FAKE_KEY)
        fanart_tv._key = None
        fanart_tv._cache = None
        fanart_tv._map = None
        self.api = FakeAPI()
        default.get_api = lambda: self.api
        self.requests = []

        def urlopen(req, timeout=None, context=None):
            self.requests.append(req)
            return _Response(_fanart_payload())

        urllib.request.urlopen = urlopen

    def _seed_release_map(self):
        fanart_tv.remember_artist('ar1', ARTIST_MBID)
        mapping = fanart_tv.load_map()
        mapping['release'][RELEASE_MBID] = RELEASE_GROUP
        fanart_tv.save_map()
        fanart_tv.remember_album('al1', RELEASE_MBID)

    def test_clearlogo_and_discart_on_artist_album_song(self):
        self._seed_release_map()
        default.list_artists()
        artist = XBMCPLUGIN.items[-1]
        self.assertEqual(artist.art.get('clearlogo'), LOGO)
        self.assertEqual(artist.art.get('fanart'), BACKGROUND)
        self.assertIn('thumb', artist.art)
        self.assertNotIn('discart', artist.art)
        self.assertTrue(self.requests)
        self.assertIn(ARTIST_MBID, self.requests[0].full_url)
        self.assertIn('api_key=%s' % FAKE_KEY, self.requests[0].full_url)

        default.add_album_item(self.api, ALBUM)
        album = XBMCPLUGIN.items[-1]
        self.assertEqual(album.art.get('clearlogo'), LOGO)
        self.assertEqual(album.art.get('discart'), CDART)
        self.assertIn('thumb', album.art)

        default.add_track_item(self.api, SONG)
        song = XBMCPLUGIN.items[-1]
        self.assertEqual(song.art.get('clearlogo'), LOGO)
        self.assertEqual(song.art.get('discart'), CDART)
        self.assertIn('thumb', song.art)
        self.assertEqual(song.getMusicInfoTag().values.get('disc'), 2)

    def test_native_mbid_fields(self):
        """0.6.0's native API uses mbzArtistId / mbzAlbumId, not musicBrainzId."""
        self.api.get_artists = lambda size=500, offset=0: [{
            'id': 'ar1',
            'name': 'Radiohead',
            'coverArt': 'ar1',
            'mbzArtistId': ARTIST_MBID,
        }]
        default.list_artists()
        artist = XBMCPLUGIN.items[-1]
        self.assertEqual(artist.art.get('clearlogo'), LOGO)

        native_album = dict(ALBUM)
        native_album.pop('musicBrainzId')
        native_album['mbzAlbumId'] = RELEASE_MBID
        fanart_tv.remember_artist('ar1', ARTIST_MBID)
        mapping = fanart_tv.load_map()
        mapping['release'][RELEASE_MBID] = RELEASE_GROUP
        fanart_tv.save_map()
        default.add_album_item(self.api, native_album)
        album = XBMCPLUGIN.items[-1]
        self.assertEqual(album.art.get('discart'), CDART)
        self.assertEqual(album.art.get('clearlogo'), LOGO)

    def test_missing_key_falls_back(self):
        FILES.data[fanart_tv.TMDB_HELPER_SETTINGS] = _settings_xml('')
        fanart_tv._key = None

        def urlopen(req, timeout=None, context=None):
            raise AssertionError('fanart.tv was called without a key')

        urllib.request.urlopen = urlopen
        default.list_artists()
        default.add_album_item(self.api, ALBUM)
        default.add_track_item(self.api, SONG)

        self.assertEqual(len(XBMCPLUGIN.items), 3)
        for item in XBMCPLUGIN.items:
            self.assertNotIn('clearlogo', item.art)
            self.assertNotIn('discart', item.art)
            self.assertIn('thumb', item.art)
        song = XBMCPLUGIN.items[-1]
        self.assertEqual(song.getMusicInfoTag().values.get('disc'), 2)

    def test_fanart_error_falls_back(self):
        def urlopen(req, timeout=None, context=None):
            raise urllib.error.URLError('fanart down')

        urllib.request.urlopen = urlopen
        default.list_artists()
        default.add_album_item(self.api, ALBUM)
        default.add_track_item(self.api, SONG)

        self.assertEqual(len(XBMCPLUGIN.items), 3)
        for item in XBMCPLUGIN.items:
            self.assertNotIn('clearlogo', item.art)
            self.assertNotIn('discart', item.art)
            self.assertIn('thumb', item.art)

    def test_fanart_http_error_falls_back(self):
        def urlopen(req, timeout=None, context=None):
            raise urllib.error.HTTPError(
                'https://webservice.fanart.tv/v3/music/' + ARTIST_MBID,
                503,
                'unavailable',
                hdrs=None,
                fp=io.BytesIO(b''),
            )

        urllib.request.urlopen = urlopen
        default.list_artists()
        default.add_album_item(self.api, ALBUM)
        self.assertEqual(len(XBMCPLUGIN.items), 2)
        for item in XBMCPLUGIN.items:
            self.assertNotIn('clearlogo', item.art)
            self.assertIn('thumb', item.art)

    def test_artist_radio_queues_plugin_playback(self):
        default.list_artists()
        labels = [label for label, _action in XBMCPLUGIN.items[-1].context]
        self.assertIn('Artist Radio', labels)

        self.api.similar = [{
            'id': 'tr9',
            'title': 'Karma Police',
            'artist': 'Radiohead',
            'album': 'OK Computer',
            'duration': 262,
            'coverArt': 'al1',
        }]
        default.play_artist_radio('ar1', 'Radiohead')
        self.assertEqual(len(XBMC.Player.played), 1)
        urls = XBMC.Player.played[0].urls
        self.assertEqual(len(urls), 1)
        self.assertIn('action=play_track', urls[0])
        self.assertIn('id=tr9', urls[0])
        self.assertNotIn('http://', urls[0])
        self.assertNotIn('https://', urls[0])

        XBMC.Player.played = []
        self.api.similar = []
        default.play_artist_radio('ar1', 'Radiohead')
        self.assertEqual(XBMC.Player.played, [])


class CoverSizeTests(unittest.TestCase):
    def test_cover_art_default_size_is_local_1000(self):
        import inspect
        from lib.navidrome_api import NavidromeAPI
        default_size = inspect.signature(
            NavidromeAPI.get_cover_art_url
        ).parameters['size'].default
        self.assertEqual(default_size, 1000)


if __name__ == '__main__':
    unittest.main()
