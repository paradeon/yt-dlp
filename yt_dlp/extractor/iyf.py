import hashlib
from urllib.parse import parse_qsl, quote, urlparse, unquote

from .common import InfoExtractor
from ..utils import ExtractorError, int_or_none, traverse_obj


class IyfIE(InfoExtractor):
    IE_NAME = 'iyf'
    _VALID_URL = r'https?://(?:www\.)?iyf\.tv/play/(?P<id>[A-Za-z0-9]+)'
    _TESTS = [{
        # Series — 8 episodes
        'url': 'https://www.iyf.tv/play/IkrUJVVAPzC',
        'info_dict': {
            'id': 'IkrUJVVAPzC',
            'title': '钟表馆事件',
            'thumbnail': r're:^https?://.*\.jpg',
            'description': str,
        },
        'playlist_count': 8,
    }, {
        # Single episode via ?mid=<numeric_episode_id>
        'url': 'https://www.iyf.tv/play/IkrUJVVAPzC?mid=1217185',
        'info_dict': {
            'id': 'IkrUJVVAPzC_ep1217185',
            'ext': 'mp4',
            'title': '钟表馆事件',
            'thumbnail': r're:^https?://.*\.jpg',
            'description': str,
        },
        'params': {'skip_download': True},
    }]

    _API_HOST = 'm10.iyf.tv'

    def _build_signed_url(self, path, params, public_key, private_key):
        # Sign over plain (insertion-order) query — must match JS get_query / uriSignature
        plain_qs = '&'.join(f'{k}={v}' for k, v in params.items())
        vv = hashlib.md5(
            f'{public_key}&{plain_qs.lower()}&{private_key}'.encode()).hexdigest()
        url_qs = '&'.join(f'{k}={quote(str(v), safe="")}' for k, v in params.items())
        return f'https://{self._API_HOST}/{path}?{url_qs}&vv={vv}&pub={public_key}'

    def _get_auth_token(self, video_id):
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

    def _extract_formats(self, play, video_id):
        formats = []
        subtitles = {}

        for c in (play.get('clarity') or []):
            path_obj = c.get('path')
            if not path_obj:
                continue
            q_title = c.get('title') or c.get('description') or 'unknown'
            tbr = int_or_none(c.get('bitrate'), scale=1000)
            for fmt in self._formats_from_path(path_obj, q_title, tbr, video_id):
                formats.append(fmt)

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

        return formats, subtitles

    def _real_extract(self, url):
        video_id = self._match_id(url)
        qs = dict(parse_qsl(urlparse(url).query))
        # mid selects a specific episode within a series by numeric media ID
        ep_mid = qs.get('mid')

        # Always fetch base page (without query) for stable signing keys
        webpage = self._download_webpage(
            f'https://www.iyf.tv/play/{video_id}', video_id)

        inject_json = self._search_json(r'injectJson\s*=\s*', webpage, 'inject JSON', video_id)
        config = traverse_obj(inject_json, ('config', 0)) or {}
        p_config = config.get('pConfig') or {}
        public_key = p_config.get('publicKey', '')
        private_keys = p_config.get('privateKey') or []
        private_key = private_keys[0] if private_keys else ''
        if not public_key or not private_key:
            raise ExtractorError('Could not extract API signing keys from page')

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
        serial_count = int_or_none(detail.get('serialCount')) or 0
        cid = detail.get('cid') or ''

        token = self._get_auth_token(video_id)

        # Multi-episode series (no specific episode requested): return playlist
        if not ep_mid and serial_count > 1:
            playlist = self._api_get('v3/video/languagesplaylist', {
                'cinema': '1',
                'vid': video_id,
                'lsk': '1',
                'taxis': '0',
                'cid': cid,
            }, public_key, private_key, video_id, 'Downloading episode list')

            entries = []
            for ep in (playlist.get('playList') or []):
                ep_id = ep.get('id')      # numeric media ID used as mid param
                ep_name = ep.get('name') or ''
                if not ep_id:
                    continue
                ep_url = f'https://www.iyf.tv/play/{video_id}?mid={ep_id}'
                entries.append(self.url_result(
                    ep_url, IyfIE,
                    f'{video_id}_ep{ep_id}',
                    f'{title} {ep_name}'.strip(),
                    url_transparent=True,
                    series=title))

            if entries:
                return self.playlist_result(
                    entries, video_id, title,
                    thumbnail=thumbnail, description=description)

        # Single video or specific episode
        result_id = f'{video_id}_ep{ep_mid}' if ep_mid else video_id

        # a=1 enables unauthenticated access (free quality); token adds VIP qualities
        # mid selects the episode; placed between id and a to match urlBuilder order
        play_params = {
            'cinema': '1',
            'id': video_id,
        }
        if ep_mid:
            play_params['mid'] = ep_mid
        play_params.update({
            'a': '1',
            'lang': 'zh-CN',
            'usersign': '1',
            'region': 'GL.',
            'device': '1',
            'isMasterSupport': '1',
        })
        if token:
            for k in ('expire', 'gid', 'sign', 'token', 'uid'):
                if k in token:
                    play_params[k] = token[k]

        play = self._api_get('v3/video/play', play_params, public_key, private_key,
                             video_id, 'Downloading play info')

        formats, subtitles = self._extract_formats(play, result_id)

        if not formats:
            raise ExtractorError('No playable streams found')

        return {
            'id': result_id,
            'title': title,
            'thumbnail': thumbnail,
            'description': description,
            'formats': formats,
            'subtitles': subtitles,
        }
