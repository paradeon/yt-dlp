import re

from .common import InfoExtractor
from ..utils import ExtractorError


class M1xdropIE(InfoExtractor):
    IE_NAME = 'm1xdrop'
    # Handles mixdrop.ag (and its variants) which redirect to m1xdrop.click
    _VALID_URL = r'https?://(?:(?:www\.)?(?:mixdrop\.(?:ag|co|to|ch|si|gl)|m1xdrop\.click))/e/(?P<id>[A-Za-z0-9]+)'
    _TESTS = [{
        'url': 'https://mixdrop.ag/e/36pr377vfqp6k8',
        'info_dict': {
            'id': '36pr377vfqp6k8',
            'ext': 'mp4',
            'title': str,
        },
        'params': {'skip_download': True},
    }]

    # Canonical host — mixdrop.ag redirects here
    _EMBED_HOST = 'https://m1xdrop.click'

    @staticmethod
    def _unpack_packer(p, a, k):
        """Decode a Dean Edwards p,a,c,k packed JavaScript string."""
        a = int(a)

        def lookup(m):
            idx = int(m.group(0), max(a, 2))
            return k[idx] if idx < len(k) and k[idx] else m.group(0)

        return re.sub(r'\w+', lookup, p)

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(
            f'{self._EMBED_HOST}/e/{video_id}', video_id,
            headers={'Referer': f'{self._EMBED_HOST}/'})

        # The player config lives inside an eval(function(p,a,c,k,e,d){...})
        # packed block.  Extract the three arguments we need.
        m = re.search(
            r"}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*\d+\s*,"
            r"\s*'((?:[^'\\]|\\.)*)'\s*\.split\s*\(\s*'\|'\s*\)",
            webpage, re.DOTALL)
        if not m:
            raise ExtractorError('Could not locate packed player script', expected=True)

        p_str = m.group(1).replace("\\'", "'")
        a_val = m.group(2)
        k_list = m.group(3).replace("\\'", "'").split('|')

        unpacked = self._unpack_packer(p_str, a_val, k_list)

        # MDCore.wurl is the signed CDN URL for the video
        wurl = self._search_regex(
            r'MDCore\.wurl\s*=\s*"([^"]+)"', unpacked, 'video URL')
        video_url = 'https:' + wurl if wurl.startswith('//') else wurl

        thumbnail = self._search_regex(
            r'MDCore\.poster\s*=\s*"([^"]+)"', unpacked, 'thumbnail', default=None)
        if thumbnail and thumbnail.startswith('//'):
            thumbnail = 'https:' + thumbnail

        title = self._og_search_title(webpage, default=video_id)

        return {
            'id': video_id,
            'title': title,
            'url': video_url,
            'thumbnail': thumbnail,
            'ext': 'mp4',
            'http_headers': {'Referer': f'{self._EMBED_HOST}/'},
        }
