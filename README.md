# ytRip

A small local web app for searching YouTube Music / YouTube and downloading tracks, albums and playlists as tagged audio files. Winamp-style UI, runs only while you have it open.

## Setup (once)

Requirements: Windows, Python 3.10+, ffmpeg, and Node.js or Deno (YouTube downloads need a JavaScript runtime).

1. Put an ffmpeg build folder (`ffmpeg-*/…/bin/ffmpeg.exe`) next to this README, or have `ffmpeg` on your PATH.
2. Double-click `setup.bat`. It creates `.venv` and installs `yt-dlp` and `ytmusicapi`.

## Use

Double-click **`ytRip.bat`**. The server starts hidden, quietly updates yt-dlp (skipped when offline) and opens `http://127.0.0.1:8765` in your browser.

- **Search**: songs, albums, playlists or artists. Toggle YT Music (default) and general YouTube.
- **Paste a link**: a YouTube / YT Music track, album, playlist or artist URL opens directly.
- **Albums, playlists, artists**: open into a checklist; tick what you want and hit *Download selected*.
- **↗** opens the track on YouTube to preview it. **✓** means it's already in your library.
- **Format**: MP3 (V0, default), M4A or Opus. Files get title/artist/album/track tags and square cover art.

Closing the tab shuts the server down once the download queue is empty (about 20 s later). The ⏻ button quits immediately. Use `ytRip-debug.bat` to run with a visible console when something goes wrong; the hidden mode logs to `ytRip.log`.

## Library layout

The library defaults to `tracks/` here and can be changed at the bottom of the UI.

```
tracks/Artist/Artist - Title.mp3                         singles
tracks/Artist/Album/01 - Title.mp3                       albums
tracks/Playlists/Playlist Name/01 - Artist - Title.mp3   playlists
```

`tracks/.archive.txt` records downloaded video IDs (powers the ✓ marker). A track whose target file already exists is skipped.

## Layout

| Path | What |
| --- | --- |
| `app/server.py` | stdlib HTTP server, API, self-update, auto-shutdown |
| `app/music.py` | search/browse (ytmusicapi for YT Music, yt-dlp for YouTube) and result dedup |
| `app/downloads.py` | 3-worker download queue: yt-dlp + ffmpeg, tags, cover art |
| `app/static/` | the UI (plain HTML/CSS/JS, no build step) |
