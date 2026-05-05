from .common import InfoExtractor
from ..utils import (
    int_or_none,
    traverse_obj,
    unified_strdate,
)


class XgCartoonIE(InfoExtractor):
    IE_NAME = 'xgcartoon'
    _VALID_URL = r'''(?x)
        https?://(?:www\.)?
        (?:
            (?:(?:xgcartoon|twxgct|cnxgct)\.com/video/[^/]+/(?P<id>[A-Za-z0-9]+)\.html)
            |(?:xgcartoon\.com/user/page_direct\?(?:[^#]*&|)chapter_id=(?P<chapter_id>[A-Za-z0-9]+))
        )
    '''
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
        'url': 'https://www.xgcartoon.com/user/page_direct?cartoon_id=mingzhentankenanjuchangbanhejiriyu-qingshangangchang&chapter_id=486aGGTZLR',
        'info_dict': {
            'id': '486aGGTZLR',
            'ext': 'mp4',
            'title': str,
            'thumbnail': r're:^https?://.*',
        },
        'params': {'skip_download': True},
    }, {
        'url': 'https://www.xgcartoon.com/video/siyueshinidehuangyanriyu-shiheigongping/AfLas2SgWG.html',
        'only_matching': True,
    }, {
        'url': 'https://www.cnxgct.com/video/mingzhentankenanjuchangbanhejiriyu-qingshangangchang/486aGGTZLR.html',
        'only_matching': True,
    }]

    # All three domains (xgcartoon, twxgct, cnxgct) serve the same content
    _PLAYER_HOST = 'pframe.xgcartoon.com'
    _CDN_HOST = 'xgct-video.bzcdn.net'

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        video_id = mobj.group('id') or mobj.group('chapter_id')

        if mobj.group('chapter_id'):
            # xgcartoon.com origin is unreliable (times out); reconstruct the
            # equivalent twxgct.com URL directly from the query parameters so
            # we never touch the origin server at all.
            cartoon_id = self._search_regex(
                r'[?&]cartoon_id=([^&#]+)', url, 'cartoon ID')
            fetch_url = f'https://www.twxgct.com/video/{cartoon_id}/{video_id}.html'
        else:
            fetch_url = url

        webpage = self._download_webpage(fetch_url, video_id)

        # The iframe src contains the CDN UUID: player.htm?vid={uuid}
        player_url = self._search_regex(
            r'iframe[^>]+src=["\']([^"\']*pframe\.[^"\']+player\.htm[^"\']*)["\']',
            webpage, 'player URL')
        vid_uuid = self._search_regex(r'[?&]vid=([0-9a-f-]{36})', player_url, 'video UUID')

        # Fetch metadata JSON served directly from the CDN (non-fatal: some videos
        # may have an accessible playlist but a missing or not-yet-uploaded info file)
        info = self._download_json(
            f'https://{self._CDN_HOST}/{vid_uuid}/video_info.json',
            video_id, 'Downloading video info', fatal=False) or {}

        m3u8_url = f'https://{self._CDN_HOST}/{vid_uuid}/playlist.m3u8'
        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            m3u8_url, video_id, 'mp4', m3u8_id='hls')

        # Use the canonical video page URL as Referer (always xgcartoon.com/video/...)
        # regardless of which domain or URL format was originally requested
        canonical_url = self._html_search_regex(
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
            webpage, 'canonical URL', default=url)
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
            'http_headers': {'Referer': canonical_url},
        }
