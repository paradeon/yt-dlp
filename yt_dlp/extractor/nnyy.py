import re

from .common import InfoExtractor
from ..utils import ExtractorError


class NnyyIE(InfoExtractor):
    IE_NAME = 'nnyy'
    # Internal API endpoint used as the canonical per-episode URL
    _VALID_URL = r'https?://(?:www\.)?nnyy\.in/_gp/(?P<series_id>\d+)/(?P<ep_slug>[^/?#]+)'
    _TESTS = [{
        # series episode
        'url': 'https://nnyy.in/_gp/20242932/ep1',
        'info_dict': {
            'id': '20242932_ep1',
            'ext': 'mp4',
            'title': str,
        },
        'params': {'skip_download': True},
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        series_id = mobj.group('series_id')
        ep_slug = mobj.group('ep_slug')
        video_id = f'{series_id}_{ep_slug}'

        data = self._download_json(url, video_id)
        video_plays = data.get('video_plays') or []
        if not video_plays:
            raise ExtractorError('No video sources found')

        m3u8_url = video_plays[0]['play_data']
        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            m3u8_url, video_id, 'mp4')

        return {
            'id': video_id,
            'title': ep_slug,
            'formats': formats,
            'subtitles': subtitles,
        }


class NnyySeriesIE(InfoExtractor):
    IE_NAME = 'nnyy:series'
    _VALID_URL = r'https?://(?:www\.)?nnyy\.in/(?:\w+)/(?P<id>\d+)\.html'
    _TESTS = [{
        # movie (single video, hd slug)
        'url': 'https://nnyy.in/dongman/20120735.html',
        'info_dict': {
            'id': '20120735',
            'ext': 'mp4',
            'title': str,
            'description': str,
        },
        'params': {'skip_download': True},
    }, {
        # multi-episode series
        'url': 'https://nnyy.in/dongman/20242932.html',
        'info_dict': {
            'id': '20242932',
            'title': str,
        },
        'playlist_mincount': 2,
    }]

    def _real_extract(self, url):
        series_id = self._match_id(url)
        webpage = self._download_webpage(url, series_id)

        title = self._html_search_regex(
            r'class="[^"]*\btitle\b[^"]*"[^>]*>\s*([^\n<]+?)\s*<',
            webpage, 'title', default=None)
        if not title:
            title = self._html_search_regex(
                r'<title>\s*[《【]?([^》】<]+?)[》】]?(?:\s*全集在线观看.*)?</title>',
                webpage, 'title', default=series_id)

        description = self._html_search_meta('description', webpage)

        # Parse episode list in document order; the page renders them reversed
        # (倒序) so we sort ep\d+ slugs numerically ourselves
        episodes = []
        seen = set()
        for m in re.finditer(r'ep_slug="([^"]+)"[^>]*><a[^>]*>([^<]+)</a>', webpage):
            ep_slug, ep_title = m.group(1), m.group(2).strip()
            if ep_slug not in seen:
                seen.add(ep_slug)
                episodes.append((ep_slug, ep_title))

        numbered = sorted(
            [(s, t) for s, t in episodes if re.match(r'^ep\d+$', s)],
            key=lambda x: int(re.search(r'\d+', x[0]).group()))

        if len(numbered) > 1:
            entries = []
            for ep_slug, ep_title in numbered:
                ep_url = f'https://nnyy.in/_gp/{series_id}/{ep_slug}'
                entries.append(self.url_result(
                    ep_url, NnyyIE, f'{series_id}_{ep_slug}',
                    f'{title} {ep_title}',
                    url_transparent=True,
                    series=title))
            return self.playlist_result(entries, series_id, title,
                                        description=description)

        # Single video: prefer hd slug, else first ep\d+, else first available
        ep_slug = next(
            (s for s, _ in episodes if s == 'hd'),
            numbered[0][0] if numbered else (episodes[0][0] if episodes else None))
        if not ep_slug:
            raise ExtractorError('No playable episodes found')

        ep_url = f'https://nnyy.in/_gp/{series_id}/{ep_slug}'
        data = self._download_json(ep_url, series_id)
        video_plays = data.get('video_plays') or []
        if not video_plays:
            raise ExtractorError('No video sources found')

        m3u8_url = video_plays[0]['play_data']
        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            m3u8_url, series_id, 'mp4')

        return {
            'id': series_id,
            'title': title,
            'description': description,
            'formats': formats,
            'subtitles': subtitles,
        }
