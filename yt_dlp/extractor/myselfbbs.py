import json
import re
import time

from .common import InfoExtractor
from ..utils import ExtractorError, int_or_none


class MyselfBBSIE(InfoExtractor):
    IE_NAME = 'myselfbbs'
    _VALID_URL = r'https?://v\.myself-bbs\.com/player/(?:play/(?P<tid>\d+)/(?P<vid>[^/?#\s]+)|(?P<id>[A-Za-z0-9_-]+))'
    _TESTS = [{
        'url': 'https://v.myself-bbs.com/player/play/44360/001',
        'info_dict': {
            'id': '44360_001',
            'ext': 'mp4',
            'title': 'Episode 1',
        },
        'params': {'skip_download': 'm3u8'},
    }, {
        'url': 'https://v.myself-bbs.com/player/AgADoggAAufkKVQ',
        'info_dict': {
            'id': 'AgADoggAAufkKVQ',
            'ext': 'mp4',
            'title': 'AgADoggAAufkKVQ',
        },
        'params': {'skip_download': 'm3u8'},
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        tid = mobj.group('tid') or ''
        vid = mobj.group('vid') or ''
        id_ = mobj.group('id') or ''
        video_id = f'{tid}_{vid}' if tid else id_

        self._download_webpage(
            url, video_id, fatal=False,
            headers={
                'Referer': 'https://myself-bbs.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            })

        for attempt in range(6):
            try:
                ws = self._request_webpage(
                    'wss://v.myself-bbs.com/ws', video_id, 'Connecting to WebSocket server',
                    headers={'Origin': 'https://v.myself-bbs.com'})
                ws.send(json.dumps({'tid': tid, 'vid': vid, 'id': id_}))
                data = json.loads(ws.recv())
                ws.close()
                break
            except ExtractorError:
                if attempt == 5:
                    raise
                wait = 2 ** attempt
                self.report_warning(f'WebSocket connection failed, retrying in {wait}s ({attempt + 1}/5)')
                time.sleep(wait)

        if data.get('status') != 'ok':
            raise ExtractorError(data.get('message') or 'WebSocket returned error', expected=True)

        m3u8_url = data['video']
        formats = self._extract_m3u8_formats(
            m3u8_url, video_id, 'mp4',
            headers={'Referer': 'https://v.myself-bbs.com/'})

        title = f'Episode {int_or_none(vid) or vid}' if vid else id_
        return {
            'id': video_id,
            'title': title,
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
    }, {
        'url': 'https://myself-bbs.com/thread-43215-1-1.html',
        'info_dict': {
            'id': '43215',
            'title': '3月的獅子 第二季',
        },
        'playlist_mincount': 22,
    }, {
        'url': 'https://myself-bbs.com/thread-44833-1-1.html',
        'info_dict': {
            'id': '44833',
            'title': '灣岸競速／灣岸Midnight',
        },
        'playlist_count': 26,
    }]

    def _real_extract(self, url):
        playlist_id = self._match_id(url)
        webpage = self._download_webpage(url, playlist_id)

        title = self._html_search_regex(
            r'<title>([^【<]+)', webpage, 'title', default=playlist_id).strip()

        list_start = webpage.find('劇集列表')
        episodes = []
        for block in re.finditer(
            r'<a\s+href="javascript:;">(?P<raw>[^<]+)</a>\s*<ul[^>]*>(?P<links>.*?)</ul>',
            webpage[list_start:] if list_start != -1 else webpage, re.DOTALL,
        ):
            raw_title = block.group('raw').strip()
            player_url = re.search(
                r'data-href="(https://v\.myself-bbs\.com/player/[^"\r\n]+)',
                block.group('links'))
            if not player_url:
                continue
            ep_m = re.match(r'第\s*(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)\s*[話话]\s*(.*)', raw_title)
            if ep_m:
                ep_label, ep_num, ep_subtitle = 'Episode', ep_m.group(1), ep_m.group(2).strip()
            else:
                ep_m = re.match(r'(\S+)\s+(\d+(?:\.\d+)?)\s*(.*)', raw_title)
                if ep_m:
                    ep_label, ep_num, ep_subtitle = ep_m.group(1), ep_m.group(2), ep_m.group(3).strip()
                else:
                    ep_label, ep_num, ep_subtitle = raw_title, None, ''
            episodes.append((ep_label, ep_num, ep_subtitle, player_url.group(1).strip()))

        pad = 2 if len(episodes) >= 10 else 0
        entries = []
        for ep_label, ep_num, ep_subtitle, ep_url in episodes:
            if ep_num is not None:
                num_str = ep_num.zfill(pad) if pad else ep_num
                ep_title = f'{ep_label} {num_str}'
            else:
                ep_title = ep_label
            if ep_subtitle:
                ep_title += f' - {ep_subtitle}'
            entries.append(self.url_result(
                ep_url, MyselfBBSIE, title=ep_title, url_transparent=True))

        if len(entries) == 1:
            entries[0]['title'] = title

        return self.playlist_result(entries, playlist_id, title)
