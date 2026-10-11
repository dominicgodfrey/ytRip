"""Download queue: 3 workers, each job is one track run through yt-dlp + ffmpeg."""
import glob
import itertools
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from yt_dlp.postprocessor import FFmpegPostProcessor, PostProcessor
from yt_dlp.utils import sanitize_filename

FORMATS = {'mp3': '0', 'm4a': None, 'opus': None}  # codec -> preferredquality ('0' = MP3 V0)
# Crop YouTube's 16:9 thumbnails to a centered square for cover art
_SQUARE = "crop='if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'"
ARCHIVE = '.archive.txt'


class _Tags(PostProcessor):
    """Overwrite yt-dlp's scraped fields with the cleaner YT Music metadata before tagging."""

    def __init__(self, tags):
        super().__init__()
        self.tags = tags

    def run(self, info):
        info.update({k: v for k, v in self.tags.items() if v})
        if self.tags.get('title'):
            info['track'] = self.tags['title']
        return [], info


class _SquareCover(FFmpegPostProcessor):
    """Crop the (already jpg-converted) thumbnail to a centered square, in place."""

    def run(self, info):
        for t in info.get('thumbnails') or []:
            path = t.get('filepath')
            if path and os.path.exists(path):
                tmp = path + '.sq.jpg'
                self.run_ffmpeg(path, tmp, ['-vf', _SQUARE, '-c:v', 'mjpeg', '-q:v', '2'])
                os.replace(tmp, path)
        return [], info


def _safe(s, fallback='Unknown'):
    return sanitize_filename(str(s or '').strip(), restricted=False).strip(' .') or fallback


def target_path(t, library):
    """Path (without extension) for a track, per the agreed folder layout."""
    artist = _safe((t.get('artist') or '').split(', ')[0], 'Unknown Artist')
    title = _safe(t.get('title'), t['id'])
    num = f'{int(t["track_number"]):02d}' if t.get('track_number') else None
    coll = t.get('collection') or {}
    if coll.get('kind') == 'album':
        album_artist = _safe((coll.get('artist') or '').split(', ')[0], artist)
        return os.path.join(library, album_artist, _safe(coll.get('title'), 'Unknown Album'),
                            f'{num} - {title}' if num else title)
    if coll.get('kind') == 'playlist':
        name = f'{artist} - {title}'
        return os.path.join(library, 'Playlists', _safe(coll.get('title'), 'Playlist'),
                            f'{num} - {name}' if num else name)
    return os.path.join(library, artist, f'{artist} - {title}')


class Queue:
    def __init__(self, ffmpeg, get_library):
        self.ffmpeg = ffmpeg
        self.get_library = get_library
        self.jobs = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=3)
        self._ids = itertools.count(1)

    # ---- archive (powers the "already have it" marker) ----
    def _archive_path(self):
        return os.path.join(self.get_library(), ARCHIVE)

    def owned(self):
        try:
            with open(self._archive_path(), encoding='utf-8') as f:
                return {line.split()[-1] for line in f if line.strip()}
        except FileNotFoundError:
            return set()

    def _record(self, vid):
        with self.lock, open(self._archive_path(), 'a', encoding='utf-8') as f:
            f.write(f'youtube {vid}\n')

    # ---- queue ----
    def busy(self):
        return any(j['status'] in ('queued', 'downloading', 'converting') for j in self.jobs.values())

    def snapshot(self):
        return [dict(j) for j in self.jobs.values()]

    def clear_finished(self):
        with self.lock:
            for k in [k for k, j in self.jobs.items() if j['status'] in ('done', 'error', 'skipped')]:
                del self.jobs[k]

    def add(self, tracks, fmt):
        fmt = fmt if fmt in FORMATS else 'mp3'
        for t in tracks:
            jid = next(self._ids)
            self.jobs[jid] = {'jid': jid, 'id': t['id'], 'title': t.get('title'), 'artist': t.get('artist'),
                              'format': fmt, 'status': 'queued', 'progress': 0, 'error': None}
            self.pool.submit(self._run, jid, t, fmt)

    def _set(self, jid, **kw):
        if jid in self.jobs:
            self.jobs[jid].update(kw)

    def _run(self, jid, t, fmt):
        library = self.get_library()
        base = target_path(t, library)
        if os.path.exists(f'{base}.{fmt}'):
            self._set(jid, status='skipped', progress=100, error='Already in library')
            return
        os.makedirs(os.path.dirname(base), exist_ok=True)

        def on_dl(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                self._set(jid, status='downloading',
                          progress=round(100 * d.get('downloaded_bytes', 0) / total) if total else 0)

        def on_pp(d):
            if d['status'] == 'started':
                self._set(jid, status='converting', progress=100)

        coll = t.get('collection') or {}
        tags = {'title': t.get('title'), 'artist': t.get('artist'),
                'album': t.get('album') or (coll.get('title') if coll.get('kind') == 'album' else None),
                'album_artist': coll.get('artist') if coll.get('kind') == 'album' else None,
                'track_number': t.get('track_number') if coll.get('kind') == 'album' else None,
                'meta_date': str(t['year']) if t.get('year') else None}
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': base.replace('%', '%%') + '.%(ext)s',
            'noplaylist': True, 'quiet': True, 'no_warnings': True, 'noprogress': True,
            'js_runtimes': {'deno': {}, 'node': {}},
            'writethumbnail': True,
            'progress_hooks': [on_dl], 'postprocessor_hooks': [on_pp],
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': fmt, 'preferredquality': FORMATS[fmt]},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'},
                {'key': 'EmbedThumbnail'},
            ],
        }
        if self.ffmpeg:
            opts['ffmpeg_location'] = self.ffmpeg
        before = set(glob.glob(glob.escape(base) + '.*'))
        for attempt in range(3):  # YouTube sporadically 403s a stream URL; a fresh extraction usually works
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.add_post_processor(_Tags(tags), when='pre_process')
                    ydl.add_post_processor(_SquareCover(ydl), when='before_dl')  # runs after the jpg convertor
                    if ydl.download([f'https://www.youtube.com/watch?v={t["id"]}']):
                        raise RuntimeError('yt-dlp reported a failure')
                self._record(t['id'])
                self._set(jid, status='done', progress=100)
                return
            except Exception as e:
                error = str(e).removeprefix('ERROR: ')[:300]
                self._set(jid, status='queued', progress=0)
        for leftover in set(glob.glob(glob.escape(base) + '.*')) - before:  # partials, thumbnails
            try:
                os.remove(leftover)
            except OSError:
                pass
        self._set(jid, status='error', error=error)
