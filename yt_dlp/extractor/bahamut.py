import glob
import os
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import parse_qs, unquote, urlparse

from .common import InfoExtractor
from ..networking.exceptions import HTTPError
from ..utils import (
    ExtractorError,
    clean_html,
    float_or_none,
    smuggle_url,
    unified_timestamp,
    unsmuggle_url,
)
from ..utils.traversal import traverse_obj


class BahamutAnimeCrazyIE(InfoExtractor):
    IE_DESC = '巴哈姆特動畫瘋 ani.gamer.com.tw'
    _VALID_URL = r'https?://ani\.gamer\.com\.tw/animeVideo\.php\?sn=(?P<id>\d+)'
    _DEVICE_ID = None

    _TESTS = [{
        'url': 'https://ani.gamer.com.tw/animeVideo.php?sn=40137',
        'info_dict': {
            'id': '40137',
            'ext': 'mp4',
            'title': '膽大黨 [1]',
            'upload_date': '20241004',
            'duration': 0.38333333333333336,
            'age_limit': 12,
            'tags': ['動作', '冒險', '奇幻', '超能力', '科幻', '喜劇', '戀愛', '青春', '血腥暴力', '靈異神怪'],
            'thumbnail': 'https://p2.bahamut.com.tw/B/2KU/19/7d54e1421935f94781555420131rolv5.JPG',
            'creators': ['山代風我'],
            'timestamp': 1728000000,
            'description': 'md5:c16931fb4d24d91b858715a2560362b5',
        },
        'params': {'noplaylist': True},
        'skip': 'geo-restricted',
    }]

    RATING_TO_AGE_LIMIT = {
        1: 0,
        2: 6,
        3: 12,
        4: 15,
        5: 18,
        6: 18,  # age-gated, needs login
    }

    @staticmethod
    def _read_firefox_device_id():
        """Read ANIME_deviceid from Firefox localStorage, bypassing the Cloudflare-protected endpoint."""
        for pattern in (
            '~/Library/Application Support/Firefox/Profiles/*/storage/default/https+++ani.gamer.com.tw/ls/data.sqlite',
            '~/.mozilla/firefox/*/storage/default/https+++ani.gamer.com.tw/ls/data.sqlite',
        ):
            for db_path in glob.glob(os.path.expanduser(pattern)):
                tmp = None
                try:
                    tmp = tempfile.mktemp(suffix='.sqlite')
                    shutil.copy2(db_path, tmp)
                    conn = sqlite3.connect(tmp)
                    row = conn.execute("SELECT value FROM data WHERE key='ANIME_deviceid'").fetchone()
                    conn.close()
                    if row:
                        val = row[0]
                        return val.decode() if isinstance(val, bytes) else val
                except Exception:
                    pass
                finally:
                    if tmp and os.path.exists(tmp):
                        os.unlink(tmp)
        return None

    def _download_device_id(self, video_id):
        try:
            return self._download_json(
                'https://ani.gamer.com.tw/ajax/getdeviceid.php', video_id,
                note='Downloading device ID', errnote='Failed to download device ID',
                impersonate=True, require_impersonation=True,
                headers=self.geo_verification_headers())['deviceid']
        except ExtractorError as e:
            if isinstance(e.cause, HTTPError) and e.cause.status == 403:
                raise ExtractorError(
                    'Cloudflare challenge detected on the device ID endpoint. '
                    'Visit ani.gamer.com.tw in your browser (Firefox/Chrome) first so the device ID '
                    'is cached, then rerun with --cookies-from-browser. '
                    'Alternatively, pass it manually via --extractor-args "BahamutAnimeCrazy:device_id=<id>"',
                    expected=True) from e
            raise

    def _real_extract(self, url):
        url, unsmuggled_data = unsmuggle_url(url, {})
        video_id = self._match_id(url)
        if not self._DEVICE_ID:
            self._DEVICE_ID = (
                self._configuration_arg('device_id', [None], casesense=True)[0]
                or self._read_firefox_device_id()
                or self._download_device_id(video_id))
            if self._DEVICE_ID:
                self.write_debug(f'Using device ID: {self._DEVICE_ID[:8]}...')

        # Read early so playlist logic can be skipped when a specific src is provided
        m3u8_src = self._configuration_arg('m3u8_src', [None], casesense=True)[0]

        # The page URL's sn may not match the actual video when the user navigated
        # within the player without the URL updating. The Akamai edge-token in the
        # m3u8 URL encodes the real video SN: hdnts=…~data={device}:{videoSn}:…
        if m3u8_src:
            try:
                hdnts = unquote(parse_qs(urlparse(m3u8_src).query).get('hdnts', [''])[0])
                m = re.search(r'~data=[^:~]+:(\d+):', hdnts)
                if m and m.group(1) != video_id:
                    self.write_debug(f'm3u8 token SN {m.group(1)} overrides page SN {video_id}')
                    video_id = m.group(1)
            except Exception:
                pass

        metadata = {}
        if api_result := self._download_json(
                'https://api.gamer.com.tw/anime/v1/video.php', video_id,
                note='Downloading video info', errnote='Failed to download video info',
                impersonate=True, query={'videoSn': video_id}).get('data'):

            metadata.update(traverse_obj(api_result, ('anime', {
                'description': ('contentHtml', {clean_html}),
                'thumbnail': 'cover',
                'tags': 'tags',
                'creators': ('director', {lambda x: [x]}),
                'title': 'title',
            })))
            playlist_id = traverse_obj(api_result, ('video', 'animeSn')) or ''
            if not m3u8_src and unsmuggled_data.get('extract_playlist') is not False and self._yes_playlist(playlist_id, video_id):
                return self.playlist_result(
                    (self.url_result(
                        smuggle_url(f'https://ani.gamer.com.tw/animeVideo.php?sn={ep["videoSn"]}', {
                            'extract_playlist': False,
                        }), ie=BahamutAnimeCrazyIE,
                        video_id=ep['videoSn'], thumbnail=ep.get('cover')) for ep in traverse_obj(
                            api_result,
                            ('anime', 'episodes', ..., ...))),
                    playlist_id=playlist_id, **metadata)

            metadata.update(traverse_obj(api_result, ('video', {
                'thumbnail': 'cover',
                'title': 'title',
                'timestamp': ('upTime', {unified_timestamp}),
                'duration': ('duration', {float_or_none(scale=60)}),
                'age_limit': ('rating', {lambda x: self.RATING_TO_AGE_LIMIT.get(x)}),
            })))

        if not m3u8_src:
            m3u8_query = {'sn': video_id, 'device': self._DEVICE_ID}
            m3u8_headers = {
                'Referer': f'https://ani.gamer.com.tw/animeVideo.php?sn={video_id}',
                'Origin': 'https://ani.gamer.com.tw',
                # XHR context: override curl_cffi's navigation defaults
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                # Extended Client Hints required by Cloudflare (Critical-Ch response header)
                'Sec-CH-UA-Arch': '"arm"',
                'Sec-CH-UA-Bitness': '"64"',
                'Sec-CH-UA-Full-Version': '"146.0.0.0"',
                'Sec-CH-UA-Full-Version-List': '"Chromium";v="146.0.0.0", "Not-A.Brand";v="24.0.0.0", "Google Chrome";v="146.0.0.0"',
                'Sec-CH-UA-Model': '""',
                'Sec-CH-UA-Platform-Version': '"15.0.0"',
                **self.geo_verification_headers(),
            }

            m3u8_webpage, urlh = self._download_webpage_handle(
                'https://ani.gamer.com.tw/ajax/m3u8.php', video_id,
                note='Downloading m3u8 URL', errnote='Failed to download m3u8 URL',
                query=m3u8_query, headers=m3u8_headers,
                impersonate=True, require_impersonation=True,
                expected_status=(400, 403))

            formats_fatal = True
            if urlh.status == 403:
                formats_fatal = False
                if urlh.headers.get('cf-mitigated'):
                    raise ExtractorError(
                        'Cloudflare Bot Management is blocking the streaming URL request. '
                        'To work around this: open Chrome DevTools (F12) → Network tab, '
                        f'load https://ani.gamer.com.tw/animeVideo.php?sn={video_id}, '
                        'find the request to m3u8.php, copy the "src" value from its JSON response, '
                        f'then rerun with: --extractor-args "BahamutAnimeCrazy:m3u8_src=<the-url>"',
                        expected=True)
                self.raise_geo_restricted(metadata_available=True)

            m3u8_info = self._parse_json(m3u8_webpage, video_id) if m3u8_webpage else {}
            error_code = traverse_obj(m3u8_info, ('error', 'code'))
            if error_code:
                if error_code == 1011:
                    formats_fatal = False
                    self.raise_geo_restricted(metadata_available=True)
                elif error_code == 1007:
                    if self._configuration_arg('device_id', casesense=True):
                        self._DEVICE_ID = self._download_device_id(video_id)
                        return self.url_result(url, ie=BahamutAnimeCrazyIE, video_id=video_id)
                    raise ExtractorError('Invalid device id!')
                elif error_code == 1017:
                    formats_fatal = False
                    self.raise_login_required(metadata_available=True)
                else:
                    raise ExtractorError(
                        traverse_obj(m3u8_info, ('error', 'message')) or 'Failed to download m3u8 URL')
            m3u8_src = m3u8_info.get('src')

        return {
            **metadata,
            'id': video_id,
            'formats': self._extract_m3u8_formats(
                m3u8_src, video_id, ext='mp4',
                fatal=m3u8_src is not None,
                headers={
                    'Origin': 'https://ani.gamer.com.tw',
                    **self.geo_verification_headers(),
                }),
            'http_headers': {'Origin': 'https://ani.gamer.com.tw'},
        }
