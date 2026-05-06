import json
import re

from .common import InfoExtractor
from ..utils import ExtractorError, int_or_none


class MyselfBBSIE(InfoExtractor):
    IE_NAME = 'myselfbbs'
    _VALID_URL = r'https?://v\.myself-bbs\.com/player/play/(?P<tid>\d+)/(?P<vid>\d+)'
    _TESTS = [{
        'url': 'https://v.myself-bbs.com/player/play/44360/001',
        'info_dict': {
            'id': '44360_001',
            'ext': 'mp4',
            'title': 'Episode 1',
        },
        'params': {'skip_download': 'm3u8'},
    }]

    def _real_extract(self, url):
        tid, vid = self._match_valid_url(url).group('tid', 'vid')
        video_id = f'{tid}_{vid}'

        self._download_webpage(
            url, video_id, headers={'Referer': 'https://myself-bbs.com/'})

        ws = self._request_webpage(
            f'wss://v.myself-bbs.com/ws', video_id, 'Connecting to WebSocket server',
            headers={'Origin': 'https://v.myself-bbs.com'})
        ws.send(json.dumps({'tid': tid, 'vid': vid, 'id': ''}))
        data = json.loads(ws.recv())
        ws.close()

        if data.get('status') != 'ok':
            raise ExtractorError(data.get('message') or 'WebSocket returned error', expected=True)

        m3u8_url = data['video']
        formats = self._extract_m3u8_formats(
            m3u8_url, video_id, 'mp4',
            headers={'Referer': 'https://v.myself-bbs.com/'})

        return {
            'id': video_id,
            'title': f'Episode {int_or_none(vid) or vid}',
            'formats': formats,
            'http_headers': {'Referer': 'https://v.myself-bbs.com/'},
        }


class MyselfBBSSeriesIE(InfoExtractor):
    IE_NAME = 'myselfbbs:series'
    _VALID_URL = r'https?://(?:www\.)?myself-bbs\.com/thread-(?P<id>\d+)-\d+-\d+\.html'
    _TESTS = [{
        'url': 'https://myself-bbs.com/thread-44360-1-1.html',
        'info_dict': {
            'id': '44360',
            'title': '3月的獅子',
        },
        'playlist_mincount': 22,
    }]

    def _real_extract(self, url):
        playlist_id = self._match_id(url)
        webpage = self._download_webpage(url, playlist_id)

        title = self._html_search_regex(
            r'<title>([^【<]+)', webpage, 'title', default=playlist_id).strip()

        episode_links = re.findall(
            r'第\s*\d+\s*[話话][^<]*(?:</[^>]+>)*\s*<ul[^>]*>\s*<li><a[^>]+data-href="(https://v\.myself-bbs\.com/player/play/[^"\r\n]+)',
            webpage)

        entries = [
            self.url_result(player_url.strip(), MyselfBBSIE)
            for player_url in episode_links
        ]

        return self.playlist_result(entries, playlist_id, title)
