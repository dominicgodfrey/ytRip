"""Search and browse: YouTube Music via ytmusicapi, general YouTube via yt-dlp.

Every result is normalized to a plain dict:
  {kind: song|album|playlist|artist, id, title, artist, album, duration, year,
   thumb, url, sources: [ytm|yt]}
"""
import re
from urllib.parse import parse_qs, urlparse, quote_plus

import yt_dlp
from ytmusicapi import YTMusic

PAGE = 20
_ytm = YTMusic()
_YTM_FILTERS = {'songs': 'songs', 'albums': 'albums', 'playlists': 'playlists', 'artists': 'artists'}
# YouTube search-results "sp" filter for playlists
_YT_PLAYLIST_SP = 'EgIQAw%3D%3D'


def _thumb(thumbs):
    return thumbs[-1]['url'] if thumbs else None


def _artists(a):
    if isinstance(a, list):
        return ', '.join(x['name'] for x in a if x.get('name'))
    return a or ''


def _song(r, source='ytm', album=None, track_number=None):
    alb = r.get('album')
    return {
        'kind': 'song', 'id': r['videoId'], 'title': r.get('title') or '',
        'artist': _artists(r.get('artists')),
        'album': album or (alb.get('name') if isinstance(alb, dict) else alb),
        'track_number': track_number or r.get('trackNumber'),
        'duration': r.get('duration_seconds'), 'year': r.get('year'),
        'thumb': _thumb(r.get('thumbnails')),
        'url': f'https://music.youtube.com/watch?v={r["videoId"]}', 'sources': [source],
    }


def _ytm_item(r):
    t = r.get('resultType')
    if t in ('song', 'video') and r.get('videoId'):
        return _song(r)
    if t == 'album':
        return {'kind': 'album', 'id': r['browseId'], 'title': r.get('title'), 'artist': _artists(r.get('artists')),
                'year': r.get('year'), 'thumb': _thumb(r.get('thumbnails')),
                'url': f'https://music.youtube.com/browse/{r["browseId"]}', 'sources': ['ytm']}
    if t == 'playlist':
        pid = r['browseId'].removeprefix('VL')
        author = r.get('author')
        return {'kind': 'playlist', 'id': pid, 'title': r.get('title'),
                'artist': author.get('name') if isinstance(author, dict) else _artists(author),
                'thumb': _thumb(r.get('thumbnails')),
                'url': f'https://music.youtube.com/playlist?list={pid}', 'sources': ['ytm']}
    if t == 'artist':
        return {'kind': 'artist', 'id': r['browseId'], 'title': r.get('artist'), 'artist': r.get('artist'),
                'thumb': _thumb(r.get('thumbnails')),
                'url': f'https://music.youtube.com/channel/{r["browseId"]}', 'sources': ['ytm']}


def _ydl_flat(url, end):
    with yt_dlp.YoutubeDL({'extract_flat': 'in_playlist', 'quiet': True, 'no_warnings': True,
                           'playlistend': end, 'js_runtimes': {'deno': {}, 'node': {}}}) as ydl:
        return ydl.extract_info(url, download=False)


def _yt_item(e):
    thumb = _thumb(e.get('thumbnails'))
    if e.get('ie_key') == 'YoutubeTab':
        return {'kind': 'playlist', 'id': e['id'], 'title': e.get('title'), 'artist': e.get('channel') or '',
                'thumb': thumb, 'url': e['url'], 'sources': ['yt']}
    return {'kind': 'song', 'id': e['id'], 'title': e.get('title') or '', 'artist': e.get('channel') or e.get('uploader') or '',
            'duration': e.get('duration'), 'thumb': thumb,
            'url': f'https://www.youtube.com/watch?v={e["id"]}', 'sources': ['yt']}


def _ytm_search(q, tab, n):
    return [i for i in map(_ytm_item, _ytm.search(q, filter=_YTM_FILTERS[tab], limit=n)) if i]


def _yt_search(q, tab, n):
    if tab == 'songs':
        url = f'ytsearch{n}:{q}'
    elif tab == 'playlists':
        url = f'https://www.youtube.com/results?search_query={quote_plus(q)}&sp={_YT_PLAYLIST_SP}'
    else:
        return []
    return [_yt_item(e) for e in (_ydl_flat(url, n).get('entries') or [])]


def dedupe(items):
    """Merge songs whose title AND artist are identical (case/whitespace-insensitive) or share an id."""
    out, seen = [], {}
    for it in items:
        keys = [('id', it['id'])]
        if it['kind'] == 'song':
            keys.append(('ta', it['title'].strip().casefold(), it['artist'].strip().casefold()))
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit:
            hit['sources'] += [s for s in it['sources'] if s not in hit['sources']]
            for k in keys:
                seen.setdefault(k, hit)
            continue
        for k in keys:
            seen[k] = it
        out.append(it)
    return out


def search(q, tab, page, ytm=True, yt=False):
    """Return the merged list for pages 1..page. Upstream APIs lack offsets, so each "More" refetches."""
    n = page * PAGE
    batches = []
    if ytm:
        batches.append(_ytm_search(q, tab, n)[:n])
    if yt:
        batches.append(_yt_search(q, tab, n)[:n])
    return {'items': dedupe([i for b in batches for i in b]), 'more': any(len(b) >= n for b in batches)}


# ---- collections -------------------------------------------------------------

def album(browse_id):
    if browse_id.startswith('OLAK5'):  # album playlist id from a pasted URL
        browse_id = _ytm.get_album_browse_id(browse_id)
    a = _ytm.get_album(browse_id)
    artist = _artists(a.get('artists'))
    tracks = []
    for i, t in enumerate(a.get('tracks') or [], 1):
        if t.get('videoId'):
            s = _song(t, album=a['title'], track_number=t.get('trackNumber') or i)
            s['year'] = a.get('year')
            s['album_artist'] = artist
            s['thumb'] = s['thumb'] or _thumb(a.get('thumbnails'))
            tracks.append(s)
    return {'kind': 'album', 'id': browse_id, 'title': a['title'], 'artist': artist, 'year': a.get('year'),
            'thumb': _thumb(a.get('thumbnails')), 'url': f'https://music.youtube.com/browse/{browse_id}',
            'tracks': tracks}


def playlist(pid, limit=500):
    pid = pid.removeprefix('VL')
    try:
        p = _ytm.get_playlist(pid, limit=limit)
        tracks = [_song(t) for t in p.get('tracks') or [] if t.get('videoId')]
        author = p.get('author')
        title, owner, thumb = p.get('title'), author.get('name') if isinstance(author, dict) else '', _thumb(p.get('thumbnails'))
    except Exception:  # not a YT Music playlist; fall back to yt-dlp
        info = _ydl_flat(f'https://www.youtube.com/playlist?list={pid}', limit)
        tracks = [_yt_item(e) for e in info.get('entries') or [] if e.get('id')]
        title, owner, thumb = info.get('title'), info.get('channel') or '', _thumb(info.get('thumbnails'))
    for i, t in enumerate(tracks, 1):
        t['track_number'] = i
    return {'kind': 'playlist', 'id': pid, 'title': title, 'artist': owner, 'thumb': thumb,
            'url': f'https://music.youtube.com/playlist?list={pid}', 'tracks': tracks}


def artist(channel_id):
    a = _ytm.get_artist(channel_id)
    name = a.get('name')
    songs = a.get('songs') or {}
    try:  # full song list when available, else the top 5 on the artist page
        tracks = [_song(t) for t in _ytm.get_playlist(songs['browseId'], limit=100)['tracks'] if t.get('videoId')]
    except Exception:
        tracks = [_song(t) for t in songs.get('results') or [] if t.get('videoId')]
    albums = []
    for key in ('albums', 'singles'):
        for r in (a.get(key) or {}).get('results') or []:
            albums.append({'kind': 'album', 'id': r['browseId'], 'title': r.get('title'), 'artist': name,
                           'year': r.get('year'), 'thumb': _thumb(r.get('thumbnails')),
                           'url': f'https://music.youtube.com/browse/{r["browseId"]}', 'sources': ['ytm'],
                           'type': r.get('type') or key[:-1].title()})
    return {'kind': 'artist', 'id': channel_id, 'title': name, 'artist': name, 'thumb': _thumb(a.get('thumbnails')),
            'url': f'https://music.youtube.com/channel/{channel_id}', 'tracks': tracks, 'albums': albums}


def resolve_url(url):
    """Map a pasted YouTube / YT Music URL to {'open': collection} or {'items': [song]}."""
    u = urlparse(url.strip())
    qs = parse_qs(u.query)
    host = (u.hostname or '').removeprefix('www.').removeprefix('m.')
    vid = (qs.get('v') or [None])[0] or (u.path.lstrip('/') if host == 'youtu.be' else None)
    if not vid and (m := re.match(r'/shorts/([\w-]{11})', u.path)):
        vid = m.group(1)
    if vid:
        d = _ytm.get_song(vid).get('videoDetails') or {}
        if not d.get('title'):
            raise ValueError('Video not found or unavailable.')
        return {'items': [{
            'kind': 'song', 'id': vid, 'title': d['title'], 'artist': d.get('author') or '',
            'duration': int(d.get('lengthSeconds') or 0) or None,
            'thumb': _thumb((d.get('thumbnail') or {}).get('thumbnails')), 'url': url,
            'sources': ['ytm' if host.startswith('music.') else 'yt']}]}
    if lst := (qs.get('list') or [None])[0]:
        return {'open': album(lst) if lst.startswith('OLAK5') else playlist(lst)}
    if m := re.match(r'/browse/(MPREb_[\w-]+)', u.path):
        return {'open': album(m.group(1))}
    if m := re.match(r'/(?:channel|browse)/(UC[\w-]{22})', u.path):
        return {'open': artist(m.group(1))}
    raise ValueError('Unrecognized URL. Paste a YouTube or YouTube Music track, album, playlist or artist link.')
