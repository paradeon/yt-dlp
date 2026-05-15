import re

from .common import InfoExtractor


class MovieffmIE(InfoExtractor):
    IE_NAME = 'movieffm'
    # Match any top-level content category (movies, tvshows, drama,
    # chinese-subtitles, etc.) but not WordPress infrastructure paths.
    _VALID_URL = r'https?://(?:www\.)?movieffm\.net/(?!(?:page|category|tag|wp-content|wp-json|wp-admin)/)(?P<cat>[a-z0-9-]+)/(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.movieffm.net/movies/hold-me-back/',
        'info_dict': {
            'id': 'hold-me-back',
            'title': '把我關起來',
            'thumbnail': r're:^https?://.*',
            'description': str,
        },
        'playlist_mincount': 2,
    }, {
        # chinese-subtitles page: iframe embed sources (no direct m3u8)
        'url': 'https://www.movieffm.net/chinese-subtitles/milk-243/',
        'info_dict': {
            'id': 'milk-243',
            'title': str,
            'thumbnail': r're:^https?://.*',
        },
        'params': {'skip_download': True},
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        # og:title includes site suffix; watch.title is cleaner when present
        title = (
            self._search_regex(r'watch\s*:\s*\{[^}]*title\s*:\s*"([^"]+)"', webpage, 'title', default=None)
            or self._og_search_title(webpage))
        # prvimg is present on movies/tvshows/drama pages; fall back to og:image
        thumbnail = (
            self._search_regex(r"prvimg\s*:\s*'([^']+)'", webpage, 'thumbnail', default=None)
            or self._og_search_thumbnail(webpage))
        description = self._og_search_description(webpage, default=None)

        # All sources are embedded in a Vue.js initialization block as a JSON array.
        # Use default=None so a missing key returns None rather than the {} fallback.
        videourls = self._search_json(
            r'videourls\s*:\s*', webpage, 'video URLs', video_id,
            contains_pattern=r'\[(?s:.+)\]', fatal=False, default=None)

        # Build source index → label map from the player tab buttons
        source_labels = {}
        for m in re.finditer(
                r"@click='play\((\d+),\d+\)'[^<]*<i[^>]*></i>"
                r"<span class='title'>([^<]+)</span>"
                r"(?:<span class='tuijian'>([^<]*)</span>)?",
                webpage):
            source_labels[int(m.group(1))] = f'{m.group(2)}{m.group(3) or ""}'

        # Series/playlist page: videourls[source_idx][ep_idx] = {name, url}
        if videourls and isinstance(videourls[0], list):
            # Source labels live in a tables:[{ht, cl}, ...] JS array on series pages
            tables = self._search_json(
                r'tables\s*:\s*', webpage, 'source labels', video_id,
                contains_pattern=r'\[(?s:.+)\]', default=None)
            if isinstance(tables, list):
                for i, item in enumerate(tables):
                    if isinstance(item, dict):
                        source_labels[i] = re.sub(r'<[^>]+>', '', item.get('ht', '')).strip()

            ep_count = max((len(src) for src in videourls if src), default=0)
            headers = {'Referer': url}

            def _entries():
                for ep_idx in range(ep_count):
                    ep_name = None
                    ep_formats = []
                    ep_subtitles = {}
                    for src_idx, src_eps in enumerate(videourls):
                        if ep_idx >= len(src_eps):
                            continue
                        ep = src_eps[ep_idx]
                        ep_url = ep.get('url')
                        if not ep_url:
                            continue
                        if ep_name is None:
                            ep_name = ep.get('name', str(ep_idx + 1))
                        fmt_id = source_labels.get(src_idx, f'src{src_idx}')
                        fmts, subs = self._extract_m3u8_formats_and_subtitles(
                            ep_url, f'{video_id}_{ep_name}', 'mp4',
                            m3u8_id=fmt_id, fatal=False, headers=headers)
                        for f in fmts:
                            f['http_headers'] = headers
                            f['protocol'] = 'm3u8'
                        ep_formats.extend(fmts)
                        self._merge_subtitles(subs, target=ep_subtitles)
                    if ep_formats:
                        yield {
                            'id': f'{video_id}_{ep_name or ep_idx + 1}',
                            'title': f'{title} {ep_name}' if ep_name else title,
                            'formats': ep_formats,
                            'subtitles': ep_subtitles,
                            'thumbnail': thumbnail,
                        }

            return self.playlist_result(_entries(), video_id, title, description,
                                        thumbnail=thumbnail)

        if videourls is not None:
            formats = []
            subtitles = {}
            for entry in videourls:
                src_idx = entry.get('source', 0)
                m3u8_url = entry.get('url')
                if not m3u8_url:
                    continue
                label = source_labels.get(src_idx, f'src{src_idx}')
                fmt_id = label
                headers = {'Referer': url}
                if entry.get('type') == 'hls':
                    fmts, subs = self._extract_m3u8_formats_and_subtitles(
                        m3u8_url, video_id, 'mp4', m3u8_id=fmt_id, fatal=False,
                        headers=headers)
                    for f in fmts:
                        f['http_headers'] = headers
                        f['protocol'] = 'm3u8'
                    formats.extend(fmts)
                    self._merge_subtitles(subs, target=subtitles)
                else:
                    formats.append({
                        'format_id': fmt_id,
                        'url': m3u8_url,
                        'ext': 'mp4',
                        'http_headers': headers,
                    })

            if not formats:
                self.raise_no_formats('No playable video sources found')

            return {
                'id': video_id,
                'title': title,
                'thumbnail': thumbnail,
                'description': description,
                'formats': formats,
                'subtitles': subtitles,
            }

        # Pages like /chinese-subtitles/ embed third-party player iframes rather
        # than direct m3u8 URLs.  Extract the videos[] array and delegate each
        # entry to the appropriate sub-extractor (Mixdrop, StreamTape, etc.).
        videos_data = self._search_json(
            r'return\s*\{iframeurl[^,]*,coverImgUrl[^,]*,cur:\d+,\s*videos\s*:\s*',
            webpage, 'embed sources', video_id,
            contains_pattern=r'\[(?s:.+?)\]', fatal=False)

        if not videos_data:
            self.raise_no_formats('No playable video sources found')

        entries = []
        for src in videos_data:
            embed_url = src.get('url', '')
            if embed_url.startswith('//'):
                embed_url = 'https:' + embed_url
            if not embed_url.startswith('http'):
                continue
            entries.append({
                '_type': 'url_transparent',
                'url': embed_url,
                'title': title,
                'thumbnail': thumbnail,
            })

        if not entries:
            self.raise_no_formats('No playable video sources found')

        if len(entries) == 1:
            return {**entries[0], 'id': video_id, 'description': description}

        return self.playlist_result(entries, video_id, title, description,
                                    thumbnail=thumbnail)
