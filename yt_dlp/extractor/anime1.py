import re

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    parse_iso8601,
    traverse_obj,
    url_or_none,
)


class Anime1IE(InfoExtractor):
    IE_NAME = 'anime1'
    _VALID_URL = r'https?://(?:www\.)?anime1\.me/(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://anime1.me/28805',
        'info_dict': {
            'id': '28805',
            'ext': 'mp4',
            'title': '淫獄團地 [05]',
            'thumbnail': r're:^https?://.*',
            'timestamp': 1777825521,
            'upload_date': '20260503',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        data_apireq = self._html_search_regex(
            r'data-apireq="([^"]+)"', webpage, 'API request data')

        api_response = self._download_json(
            'https://v.anime1.me/api', video_id,
            data=f'd={data_apireq}'.encode(),
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': url,
            })

        src = traverse_obj(api_response, ('s', 0, 'src'))
        if not src:
            raise ExtractorError('Could not find video URL in API response')

        video_url = 'https:' + src if src.startswith('//') else src
        if not url_or_none(video_url):
            raise ExtractorError('Invalid video URL extracted')

        title = self._og_search_title(webpage)
        thumbnail = self._html_search_regex(
            r'<video[^>]+poster="([^"]+)"', webpage, 'thumbnail', default=None)
        timestamp = parse_iso8601(self._html_search_regex(
            r'<time[^>]+datetime="([^"]+)"', webpage, 'upload date', default=None))

        return {
            'id': video_id,
            'title': title,
            'url': video_url,
            'ext': 'mp4',
            'thumbnail': thumbnail,
            'timestamp': timestamp,
            'http_headers': {'Referer': 'https://anime1.me/'},
        }


class Anime1PlaylistIE(InfoExtractor):
    IE_NAME = 'anime1:playlist'
    _VALID_URL = r'https?://(?:www\.)?anime1\.me/(?:category/(?P<slug>[^?#]+)|\?cat=(?P<id>\d+))'
    _TESTS = [{
        'url': 'https://anime1.me/?cat=1864',
        'info_dict': {
            'id': '1864',
            'title': str,
        },
        'playlist_mincount': 5,
    }, {
        'url': 'https://anime1.me/category/2026%E5%B9%B4%E6%98%A5%E5%AD%A3/%E6%B7%AB%E7%8D%84%E5%9C%98%E5%9C%B0',
        'only_matching': True,
    }]

    def _entries(self, url, playlist_id):
        page_url = url
        for page_num in range(1, 100):
            webpage = self._download_webpage(
                page_url, playlist_id, f'Downloading page {page_num}')

            main_match = re.search(r'<main[^>]*>(.*?)</main>', webpage, re.DOTALL)
            if not main_match:
                break

            episode_urls = re.findall(
                r'href="(https://(?:www\.)?anime1\.me/(\d+))"',
                main_match.group(1))
            seen = set()
            for ep_url, ep_id in episode_urls:
                if ep_id not in seen:
                    seen.add(ep_id)
                    yield self.url_result(ep_url, Anime1IE, video_id=ep_id)

            # WordPress pagination: ?cat=N&paged=N or /category/slug/page/N/
            if '?cat=' in url:
                next_page = re.search(
                    r'href="[^"]*\?cat=\d+(?:&(?:amp;)?paged=(\d+))?[^"]*" class="[^"]*next[^"]*"',
                    webpage)
                if not next_page:
                    break
                next_num = int(next_page.group(1) or 2)
                base = re.sub(r'&paged=\d+', '', url)
                page_url = f'{base}&paged={next_num}'
            else:
                next_page = re.search(
                    r'href="([^"]+/page/\d+/[^"]*)"[^>]*class="[^"]*next[^"]*"',
                    webpage)
                if not next_page:
                    break
                page_url = next_page.group(1)

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        playlist_id = mobj.group('id') or mobj.group('slug')

        webpage = self._download_webpage(url, playlist_id)
        title = (self._html_search_regex(
            r'<h1[^>]*>([^<]+)</h1>', webpage, 'title', default=None)
            or self._og_search_title(webpage, default=None)
            or playlist_id)

        return self.playlist_result(
            self._entries(url, playlist_id), playlist_id, title)
