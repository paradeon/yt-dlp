import re

from .common import InfoExtractor


class TwoRkIE(InfoExtractor):
    IE_NAME = '2rk'
    _VALID_URL = r'https?://(?:www\.)?2rk\.cc/detail/(?P<anime_id>[^/?#]+)[^#]*[?&]id=(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://www.2rk.cc/detail/9UUIc4kBOQ_doUrM32po?id=1',
        'info_dict': {
            'id': '9UUIc4kBOQ_doUrM32po_1',
            'ext': 'mp4',
            'title': '福音战士新剧场版：破 第01话',
            'thumbnail': r're:^https?://.*\.webp$',
        },
        'params': {'skip_download': True},
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        anime_id = mobj.group('anime_id')
        ep_id = mobj.group('id')
        video_id = f'{anime_id}_{ep_id}'

        webpage = self._download_webpage(url, video_id)

        page_data = self._search_json(r'const pageData=', webpage, 'page data', video_id)
        m3u8_url = self._search_regex(
            r'h\.loadSource\("([^"]+)"\)', webpage, 'm3u8 URL')

        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            m3u8_url, video_id, 'mp4')

        # The /saber key URI in the m3u8 is a decoy.  The actual AES-128 key
        # is hardcoded in the site's h.js player (DataView constructor sequence).
        hls_aes = {'key': '1fc05934f95add1cc253421b9b94b70a'}
        for fmt in formats:
            fmt['hls_aes'] = hls_aes

        title = f'{page_data.get("animeName", "")} {page_data.get("currentEpisodeName", "")}'.strip()

        return {
            'id': video_id,
            'title': title,
            'thumbnail': f'https://www.2rk.cc/video/{anime_id}/{ep_id}.webp',
            'formats': formats,
            'subtitles': subtitles,
        }


class TwoRkSeriesIE(InfoExtractor):
    IE_NAME = '2rk:series'
    _VALID_URL = r'https?://(?:www\.)?2rk\.cc/detail/(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.2rk.cc/detail/ZUUIc4kBOQ_doUrM32iF',
        'info_dict': {
            'id': 'ZUUIc4kBOQ_doUrM32iF',
            'title': '新世纪福音战士',
            'thumbnail': r're:^https?://.*\.webp$',
        },
        'playlist_count': 26,
    }]

    def _real_extract(self, url):
        anime_id = self._match_id(url)
        # Fetch without ?id — server defaults to ep 1 and includes full episode list
        webpage = self._download_webpage(
            f'https://www.2rk.cc/detail/{anime_id}', anime_id)

        page_data = self._search_json(r'const pageData=', webpage, 'page data', anime_id)
        title = page_data.get('animeName', anime_id)

        entries = []
        seen = set()
        for ep_id, ep_title in re.findall(
            rf'href="/detail/{re.escape(anime_id)}\?id=(\d+)"[^>]*title="([^"]+)"',
            webpage,
        ):
            if ep_id in seen:
                continue
            seen.add(ep_id)
            ep_url = f'https://www.2rk.cc/detail/{anime_id}?id={ep_id}'
            entries.append(self.url_result(
                ep_url, TwoRkIE,
                f'{anime_id}_{ep_id}',
                f'{title} {ep_title}',
                url_transparent=True,
                series=title))

        entries.sort(key=lambda e: int(e['id'].rsplit('_', 1)[-1]))

        return self.playlist_result(
            entries, anime_id, title,
            thumbnail=f'https://www.2rk.cc/video/{anime_id}/index.webp')
