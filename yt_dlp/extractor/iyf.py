import hashlib
import json
import re
from urllib.parse import parse_qsl, quote, unquote

from .common import InfoExtractor
from ..utils import ExtractorError, traverse_obj


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
        # Build plain query string (insertion-order, no URL-encoding)
        plain_qs = '&'.join(f'{k}={v}' for k, v in params.items())
        sign_input = f'{public_key}&{plain_qs.lower()}&{private_key}'
        vv = hashlib.md5(sign_input.encode()).hexdigest()
        # URL: values may need encoding; pub/vv are alphanumeric so safe
        url_qs = '&'.join(f'{k}={quote(str(v), safe="")}' for k, v in params.items())
        return f'https://{self._API_HOST}/{path}?{url_qs}&vv={vv}&pub={public_key}'

    def _get_auth_token(self, video_id):
        """Read {expire,gid,sign,token,uid} from the dn_temp browser cookie."""
        cookies = self._get_cookies('https://www.iyf.tv/')
        dn_temp = cookies.get('dn_temp')
        if not dn_temp:
            return None
        # dn_temp value is a URL query string produced by JSONtoQueryString:
        #   __t=<url-encoded JSON>&token=<token-str>
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

        # Auth token from dn_temp cookie (required for all videos on this platform)
        token = self._get_auth_token(video_id)
        if not token:
            self.raise_login_required(
                'iyf.tv requires a paid account — log in via your browser and pass '
                '--cookies-from-browser or --cookies')

        # Play request — parameter insertion order replicates JS urlBuilder + appendUserInfo
        # Base params from video-media endpoint config (cinema first, then overrides)
        play_params = {
            'cinema': '1',
            'id': video_id,
            'a': '0',
            'lang': 'zh-CN',
            'usersign': '1',
            'region': 'GL.',
            'device': '1',
            'isMasterSupport': '1',
        }
        # Token fields appended last (order from Object.assign({}, t.token, {uid})):
        # expire, gid, sign, token, uid
        for k in ('expire', 'gid', 'sign', 'token', 'uid'):
            if k in token:
                play_params[k] = token[k]

        play = self._api_get('v3/video/play', play_params, public_key, private_key,
                             video_id, 'Downloading play info')

        stream_url = play.get('result')
        if not stream_url:
            raise ExtractorError('No stream URL in play response')

        if play.get('isHls', True):
            formats, subtitles = self._extract_m3u8_formats_and_subtitles(
                stream_url, video_id, 'mp4')
        else:
            formats = [{'url': stream_url}]
            subtitles = {}

        backup_url = play.get('backup')
        if backup_url:
            formats.append({'url': backup_url, 'preference': -1, 'format_id': 'backup'})

        return {
            'id': video_id,
            'title': title,
            'thumbnail': thumbnail,
            'description': description,
            'formats': formats,
            'subtitles': subtitles,
        }
