import hashlib
from urllib.parse import parse_qsl, quote, unquote

from .common import InfoExtractor
from ..utils import ExtractorError, int_or_none, traverse_obj


class IyfIE(InfoExtractor):
    IE_NAME = 'iyf'
    _VALID_URL = r'https?://(?:www\.)?iyf\.tv/play/(?P<id>[A-Za-z0-9]+)'
    _TESTS = [{
        'url': 'https://www.iyf.tv/play/IkrUJVVAPzC',
        'info_dict': {
            'id': 'IkrUJVVAPzC',
            'ext': 'mp4',
            'title': '钟表馆事件',
            'thumbnail': r're:^https?://.*\.jpg',
            'description': str,
        },
        'params': {'skip_download': True},
    }]

    _API_HOST = 'm10.iyf.tv'

    def _build_signed_url(self, path, params, public_key, private_key):
        # Sign over plain (insertion-order) query — must match JS get_query / appendUserInfo
        plain_qs = '&'.join(f'{k}={v}' for k, v in params.items())
        vv = hashlib.md5(
            f'{public_key}&{plain_qs.lower()}&{private_key}'.encode()).hexdigest()
        url_qs = '&'.join(f'{k}={quote(str(v), safe="")}' for k, v in params.items())
        return f'https://{self._API_HOST}/{path}?{url_qs}&vv={vv}&pub={public_key}'

    def _get_auth_token(self, video_id):
        """Extract {expire,gid,sign,token,uid} from the dn_temp browser cookie."""
        cookies = self._get_cookies('https://www.iyf.tv/')
        dn_temp = cookies.get('dn_temp')
        if not dn_temp:
            return None
        # dn_temp value is JSONtoQueryString(session): __t=<url-encoded-json>&token=...
        parsed = dict(parse_qsl(dn_temp.value, keep_blank_values=True))
        raw_t = parsed.get('__t') or parsed.get('%5F%5Ft')
        if not raw_t:
            return None
        t_obj = self._parse_json(unquote(raw_t), video_id, fatal=False)
        if not t_obj or not t_obj.get('uid'):
            return None
        return {k: t_obj[k] for k in ('expire', 'gid', 'sign', 'token', 'uid') if k in t_obj}

    def _api_get(self, path, params, public_key, private_key, video_id, note=None):
        url = self._build_signed_url(path, params, public_key, private_key)
        data = self._download_json(url, video_id, note or f'Downloading {path}',
                                   headers={'Referer': 'https://www.iyf.tv/'})
        code = traverse_obj(data, ('data', 'code'))
        msg = traverse_obj(data, ('data', 'msg')) or ''
        info = traverse_obj(data, ('data', 'info')) or []
        if code != 0 or not info or info[0] is None:
            raise ExtractorError(f'{msg} (code {code})')
        return info[0]

    def _formats_from_path(self, path_obj, quality_title, tbr, video_id):
        """Yield format dicts from a single path object."""
        if not path_obj or not path_obj.get('result'):
            return
        stream_url = path_obj['result']
        is_hls = path_obj.get('isHls', True)
        fmt_base = {
            'format_id': quality_title,
            'tbr': tbr,
        }
        if is_hls:
            fmts, subs = self._extract_m3u8_formats_and_subtitles(
                stream_url, video_id, 'mp4', m3u8_id=f'hls-{quality_title}',
                fatal=False)
            for f in fmts:
                yield {**f, **fmt_base}
        else:
            yield {**fmt_base, 'url': stream_url}

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        inject_json = self._search_json(r'injectJson\s*=\s*', webpage, 'inject JSON', video_id)
        config = traverse_obj(inject_json, ('config', 0)) or {}
        p_config = config.get('pConfig') or {}
        public_key = p_config.get('publicKey', '')
        private_keys = p_config.get('privateKey') or []
        private_key = private_keys[0] if private_keys else ''
        if not public_key or not private_key:
            raise ExtractorError('Could not extract API signing keys from page')

        # Video metadata
        detail = self._api_get('v3/video/detail', {
            'cinema': '1',
            'device': '1',
            'player': 'CkPlayer',
            'tech': 'HLS',
            'country': 'HU',
            'lang': 'cns',
            'v': '1',
            'id': video_id,
            'region': 'GL.',
        }, public_key, private_key, video_id, 'Downloading video info')

        title = detail.get('title') or video_id
        thumbnail = detail.get('imgPath')
        description = detail.get('contxt')

        # Try to get auth token for VIP quality access (optional)
        token = self._get_auth_token(video_id)

        # a=1 enables unauthenticated access (free quality); a=0 requires auth
        play_params = {
            'cinema': '1',
            'id': video_id,
            'a': '1',
            'lang': 'zh-CN',
            'usersign': '1',
            'region': 'GL.',
            'device': '1',
            'isMasterSupport': '1',
        }
        if token:
            for k in ('expire', 'gid', 'sign', 'token', 'uid'):
                if k in token:
                    play_params[k] = token[k]

        play = self._api_get('v3/video/play', play_params, public_key, private_key,
                             video_id, 'Downloading play info')

        formats = []
        subtitles = {}

        # clarity[] lists all quality options; only entries with path != null are accessible
        for c in (play.get('clarity') or []):
            path_obj = c.get('path')
            if not path_obj:
                continue
            q_title = c.get('title') or c.get('description') or 'unknown'
            tbr = int_or_none(c.get('bitrate'), scale=1000)
            for fmt in self._formats_from_path(path_obj, q_title, tbr, video_id):
                formats.append(fmt)

        # Fall back to flvPathList if clarity yielded nothing
        if not formats:
            for entry in (play.get('flvPathList') or []):
                if entry.get('type') != 0:
                    continue  # type=1 is an ad image
                is_hls = entry.get('isHls', True)
                stream_url = entry.get('result')
                if not stream_url:
                    continue
                if is_hls:
                    fmts, subs = self._extract_m3u8_formats_and_subtitles(
                        stream_url, video_id, 'mp4', fatal=False)
                    formats.extend(fmts)
                    self._merge_subtitles(subs, target=subtitles)
                else:
                    formats.append({'url': stream_url})

        if not formats:
            raise ExtractorError('No playable streams found')

        return {
            'id': video_id,
            'title': title,
            'thumbnail': thumbnail,
            'description': description,
            'formats': formats,
            'subtitles': subtitles,
        }
