from .common import InfoExtractor
from ..utils import (
    int_or_none,
    parse_iso8601,
    traverse_obj,
    unified_strdate,
)


class XgCartoonIE(InfoExtractor):
    IE_NAME = 'xgcartoon'
    _VALID_URL = r'https?://(?:www\.)?(?:xgcartoon|twxgct)\.com/video/[^/]+/(?P<id>[A-Za-z0-9]+)\.html'
    _TESTS = [{
        'url': 'https://www.twxgct.com/video/siyueshinidehuangyanriyu-shiheigongping/AfLas2SgWG.html',
        'info_dict': {
            'id': 'AfLas2SgWG',
            'ext': 'mp4',
            'title': '第04话 启程',
            'thumbnail': r're:^https?://.*\.jpg',
            'upload_date': '20230321',
        },
    }, {
        'url': 'https://www.xgcartoon.com/video/siyueshinidehuangyanriyu-shiheigongping/AfLas2SgWG.html',
        'only_matching': True,
    }]

    # Both twxgct.com and xgcartoon.com serve the same content
    _PLAYER_HOST = 'pframe.xgcartoon.com'
    _CDN_HOST = 'xgct-video.bzcdn.net'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        # The iframe src contains the CDN UUID: player.htm?vid={uuid}
        player_url = self._search_regex(
            r'iframe[^>]+src=["\']([^"\']*pframe\.[^"\']+player\.htm[^"\']*)["\']',
            webpage, 'player URL')
        vid_uuid = self._search_regex(r'[?&]vid=([0-9a-f-]{36})', player_url, 'video UUID')

        # Fetch metadata JSON served directly from the CDN
        info = self._download_json(
            f'https://{self._CDN_HOST}/{vid_uuid}/video_info.json',
            video_id, 'Downloading video info')

        m3u8_url = f'https://{self._CDN_HOST}/{vid_uuid}/playlist.m3u8'
        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            m3u8_url, video_id, 'mp4', m3u8_id='hls')

        thumbnail = f'https://{self._CDN_HOST}/{vid_uuid}/{info.get("thumbnailFileName", "thumbnail.jpg")}'

        return {
            'id': video_id,
            'title': info.get('title') or self._og_search_title(webpage),
            'thumbnail': thumbnail,
            'duration': int_or_none(info.get('length')),
            'upload_date': unified_strdate(traverse_obj(info, 'dateUploaded')),
            'view_count': int_or_none(info.get('views')),
            'formats': formats,
            'subtitles': subtitles,
            'http_headers': {'Referer': url},
        }
