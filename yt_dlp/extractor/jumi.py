import base64
import re

from .common import InfoExtractor
from ..networking.impersonate import ImpersonateTarget
from ..utils import (
    ExtractorError,
    int_or_none,
    traverse_obj,
    url_or_none,
    urljoin,
)


class JumiIE(InfoExtractor):
    IE_NAME = 'jumi'
    _VALID_URL = r'https?://jumi\.su/play/(?P<id>\d+-\d+-\d+)\.html'
    _TESTS = [{
        'url': 'https://jumi.su/play/22421-1-1.html',
        'info_dict': {
            'id': '22421-1-1',
            'ext': 'mp4',
            'title': str,
        },
        'params': {
            'skip_download': True,
        },
    }]

    @staticmethod
    def _mac_unescape(encoded):
        """Decode MaCMS mac_escape encoding (%uXXXX Unicode, %XX ASCII percent encoding)"""
        result = []
        i = 0
        while i < len(encoded):
            if encoded[i] == '%' and i + 5 < len(encoded) and encoded[i + 1] == 'u':
                result.append(chr(int(encoded[i + 2:i + 6], 16)))
                i += 6
            elif encoded[i] == '%' and i + 2 < len(encoded):
                result.append(chr(int(encoded[i + 1:i + 3], 16)))
                i += 3
            else:
                result.append(encoded[i])
                i += 1
        return ''.join(result)

    def _decode_url(self, raw_url, encrypt):
        if encrypt == 1:
            return self._mac_unescape(raw_url)
        elif encrypt == 2:
            return self._mac_unescape(base64.b64decode(raw_url).decode())
        return raw_url

    @staticmethod
    def _detect_encrypt(raw_url):
        """Infer MaCMS encrypt mode from URL format when not available from HTML."""
        if raw_url.startswith('http://') or raw_url.startswith('https://'):
            return 0
        if '%u' in raw_url:
            return 1
        try:
            decoded = base64.b64decode(raw_url + '==').decode('utf-8', errors='replace')
            if decoded.startswith('http') or '%u' in decoded:
                return 2
        except Exception:
            pass
        return 0

    # jumi.su is protected by Cloudflare's managed challenge, which requires
    # JavaScript execution in a real browser. Pass cookies exported from the
    # browser that already passed the Cloudflare check, e.g.:
    #   yt-dlp --cookies-from-browser firefox <URL>
    # Note: cookies are bound to the browser's full fingerprint; use the same
    # browser that originally passed the challenge.
    _IMPERSONATE_TARGET = ImpersonateTarget('firefox')

    def _real_extract(self, url):
        video_id = self._match_id(url)
        show_id_str, source_str, ep_str = video_id.split('-')
        show_id = int(show_id_str)
        source_idx = int(source_str) - 1  # 1-based → 0-based
        ep_idx = int(ep_str) - 1

        show_title = ''
        thumbnail = None
        from_player = ''
        raw_url = None
        server = ''
        encrypt = 0
        ep_name = ''

        # MaCMS exposes a JSON API that TVBox clients use. Try it first; a
        # browser-like fingerprint is enough to pass Cloudflare for the API
        # even without a challenge cookie (unlike the interactive play page).
        api_data = self._download_json(
            urljoin(url, f'/api.php/provide/vod/?ac=detail&ids={show_id}'),
            video_id, 'Downloading video API', fatal=False,
            impersonate=self._IMPERSONATE_TARGET)

        vod = traverse_obj(api_data, ('list', 0)) or {}
        if vod:
            show_title = vod.get('vod_name') or ''
            thumbnail = vod.get('vod_pic') or None

            # vod_play_url: "ep1$url1#ep2$url2#..." groups separated by "$$$" per source
            # vod_play_from: source names, also "$$$"-separated
            play_url_groups = (vod.get('vod_play_url') or '').split('$$$')
            play_from_raw = vod.get('vod_play_from') or ''
            # Some MaCMS forks use "$$$", others use "|" for vod_play_from
            play_from = (play_from_raw.split('$$$')
                         if '$$$' in play_from_raw else play_from_raw.split('|'))

            if source_idx < len(play_from):
                from_player = play_from[source_idx]
            if source_idx < len(play_url_groups):
                episodes = play_url_groups[source_idx].split('#')
                if ep_idx < len(episodes):
                    parts = episodes[ep_idx].split('$', 1)
                    if len(parts) == 2:
                        ep_name, raw_url = parts
                    else:
                        raw_url = parts[0]

        if raw_url:
            encrypt = self._detect_encrypt(raw_url)
        else:
            # Fall back to scraping the HTML play page (requires Cloudflare bypass)
            try:
                webpage = self._download_webpage(
                    url, video_id, impersonate=self._IMPERSONATE_TARGET)
            except Exception as e:
                if '403' in str(e):
                    raise ExtractorError(
                        'Could not reach the MaCMS API and the play page is protected by '
                        'Cloudflare\'s managed challenge. Open the page in Firefox, pass the '
                        'challenge, then re-run with --cookies-from-browser firefox',
                        expected=True) from e
                raise

            player_data = self._search_json(
                r'var\s+player_aaaa\s*=', webpage, 'player data', video_id)

            encrypt = int_or_none(player_data.get('encrypt')) or 0
            raw_url = player_data.get('url') or ''
            from_player = from_player or player_data.get('from') or ''
            server = player_data.get('server') or ''

            if not show_title:
                vod_data = player_data.get('vod_data') or {}
                show_title = traverse_obj(vod_data, 'vod_name') or self._og_search_title(webpage)
            if not thumbnail:
                thumbnail = self._og_search_thumbnail(webpage)
            if not ep_name:
                ep_line = self._search_regex(
                    r'当前播放[：:：]+</span>\s*(.*?)\s*</li>',
                    webpage, 'episode line', default=None)
                if ep_line and show_title and ep_line.startswith(show_title):
                    ep_name = ep_line[len(show_title):].lstrip(' -—').strip()

        video_url = self._decode_url(raw_url, encrypt)

        if show_title and ep_name:
            title = f'{show_title} - {ep_name}'
        else:
            title = show_title or ep_name or video_id

        # Fetch playerconfig.js to determine whether the URL needs a parse service
        cfg_js = self._download_webpage(
            urljoin(url, '/static/js/playerconfig.js'),
            video_id, 'Downloading player config',
            fatal=False, impersonate=self._IMPERSONATE_TARGET) or ''

        ps = 0
        parse_url = ''
        if cfg_js and from_player:
            m = re.search(
                r'MacPlayerConfig\.player_list\s*=\s*(\{.+?\})\s*,\s*MacPlayerConfig\.downer_list',
                cfg_js, re.DOTALL)
            if m:
                player_list = self._parse_json(m.group(1), video_id, fatal=False) or {}
                player = player_list.get(from_player) or {}
                ps = int_or_none(player.get('ps')) or 0
                parse_url = player.get('parse') or ''

        # ps=1: video URL must be sent through an external parse/relay service
        if ps == 1 and parse_url and video_url:
            return self.url_result(parse_url + video_url, video_id=video_id, title=title)

        if server:
            video_url = server + video_url

        if not url_or_none(video_url):
            raise ExtractorError('Could not extract a valid video URL')

        if '.m3u8' in video_url:
            formats, subtitles = self._extract_m3u8_formats_and_subtitles(
                video_url, video_id, 'mp4')
            return {
                'id': video_id,
                'title': title,
                'thumbnail': thumbnail,
                'formats': formats,
                'subtitles': subtitles,
            }

        if re.search(r'\.mp4(\?|$)', video_url) or '/mp4/' in video_url:
            return {
                'id': video_id,
                'title': title,
                'thumbnail': thumbnail,
                'url': video_url,
                'ext': 'mp4',
            }

        # Fallback for iframe embeds or unknown URL types
        return self.url_result(video_url, video_id=video_id, title=title)
