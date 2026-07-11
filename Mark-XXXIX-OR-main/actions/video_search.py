"""
video_search.py — Multi-platform video search and playback for JARVIS.

YouTube : scrape video results → build HTML page → open in user's browser
Others  : open platform search page directly in user's browser

Platforms: YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook,
           Twitch, Vimeo, Dailymotion, Rumble
"""

import json
import re
import sys
import time
import subprocess
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote_plus

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"


def _load_config() -> dict:
    try:
        return json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_browser_exe() -> str:
    cfg     = _load_config()
    browser = cfg.get("default_browser", "msedge").strip().lower()
    exe_map = {"msedge": "msedge", "edge": "msedge", "chrome": "chrome",
               "firefox": "firefox", "brave": "brave"}
    exe     = exe_map.get(browser, "msedge")
    if shutil.which(exe):
        return exe
    candidates = {
        "msedge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
        "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
        "firefox":[r"C:\Program Files\Mozilla Firefox\firefox.exe"],
    }
    for path in candidates.get(exe, []):
        if Path(path).exists():
            return path
    return ""


def _open_url(url: str) -> None:
    """Open a URL in the user's default browser — robust multi-method."""
    print(f"[VideoSearch] Opening in browser: {url[:100]}")
    import os as _os

    # For local file:// URLs — use os.startfile (Windows native, works from any thread)
    if url.startswith("file://"):
        try:
            local_path = url.replace("file:///", "").replace("file://", "").replace("/", "\\")
            _os.startfile(local_path)
            print(f"[VideoSearch] Opened local file via os.startfile")
            time.sleep(0.8)
            return
        except Exception as e:
            print(f"[VideoSearch] os.startfile failed: {e} — trying webbrowser")
        try:
            import webbrowser
            webbrowser.open(url)
            print("[VideoSearch] Opened via webbrowser (file)")
            time.sleep(0.8)
            return
        except Exception as e:
            print(f"[VideoSearch] webbrowser failed: {e}")
        return

    # For http/https URLs — try browser exe, then webbrowser module
    exe = _get_browser_exe()
    opened = False

    if exe:
        try:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opened = True
            print(f"[VideoSearch] Launched with: {exe}")
        except Exception as e:
            print(f"[VideoSearch] exe launch failed: {e}")

    if not opened:
        try:
            import webbrowser
            webbrowser.open(url)
            opened = True
            print("[VideoSearch] Launched with webbrowser module")
        except Exception as e:
            print(f"[VideoSearch] webbrowser failed: {e}")

    if not opened:
        # Last resort — Windows shell
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False
            )
            print("[VideoSearch] Launched with cmd start")
        except Exception as e:
            print(f"[VideoSearch] cmd start failed: {e}")

    time.sleep(0.8)


# ── YouTube scraping ──────────────────────────────────────────────────────────

def _yt_scrape_videos(query: str, max_results: int = 8) -> list[dict]:
    """
    Scrape YouTube search results and return a list of video dicts:
    {video_id, title, channel, thumbnail_url, watch_url, duration}
    """
    if not _REQUESTS_OK:
        return []
    url = (f"https://www.youtube.com/results"
           f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}")
    try:
        r    = requests.get(url, headers=_HEADERS, timeout=10)
        html = r.text

        # Extract video IDs (deduplicated, no Shorts)
        ids  = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        seen = set()
        unique_ids = []
        for vid in ids:
            if vid in seen:
                continue
            seen.add(vid)
            if f"/shorts/{vid}" in html:
                continue
            unique_ids.append(vid)
            if len(unique_ids) >= max_results:
                break

        if not unique_ids:
            return []

        # Extract titles — paired with videoIds in the JSON
        titles   = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        lengths  = re.findall(r'"lengthText":\{"accessibility":[^}]+\},"simpleText":"([^"]+)"', html)

        results = []
        for i, vid in enumerate(unique_ids):
            title   = titles[i]   if i < len(titles)   else query
            channel = channels[i] if i < len(channels) else "Unknown"
            dur     = lengths[i]  if i < len(lengths)  else ""
            results.append({
                "video_id":      vid,
                "title":         title,
                "channel":       channel,
                "duration":      dur,
                "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                "watch_url":     f"https://www.youtube.com/watch?v={vid}",
            })
        return results

    except Exception as e:
        print(f"[VideoSearch] YT scrape failed: {e}")
    return []


# ── HTML results page builder ─────────────────────────────────────────────────

def _build_results_page(query: str, videos: list[dict], platform: str = "YouTube") -> str:
    """
    Build a self-contained HTML results page with video thumbnails and titles.
    Each card links directly to the video. Saved as a temp file and opened in browser.
    Returns the file:// URL of the created HTML page.
    """
    cards_html = ""
    for v in videos:
        title   = v["title"].replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        channel = v.get("channel", "").replace("<", "&lt;")
        dur     = v.get("duration", "")
        thumb   = v.get("thumbnail_url", "")
        href    = v.get("watch_url", "#")
        cards_html += f"""
        <a class="card" href="{href}" target="_blank">
            <div class="thumb-wrap">
                <img src="{thumb}" alt="{title}" loading="lazy" onerror="this.src='https://via.placeholder.com/320x180/001a2e/00d4ff?text=No+Thumbnail'">
                {"<span class='dur'>" + dur + "</span>" if dur else ""}
            </div>
            <div class="info">
                <div class="title">{title}</div>
                <div class="channel">{channel}</div>
            </div>
        </a>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS — {platform} Results: {query}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#00060a;color:#8ffcff;font-family:'Segoe UI',sans-serif;padding:20px}}
  h1{{color:#00d4ff;font-size:1.2rem;margin-bottom:4px;letter-spacing:1px}}
  .sub{{color:#3a8a9a;font-size:.85rem;margin-bottom:20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
  .card{{background:#010d14;border:1px solid #0d3347;border-radius:8px;overflow:hidden;
         text-decoration:none;color:inherit;transition:border-color .2s,transform .15s}}
  .card:hover{{border-color:#00d4ff;transform:translateY(-2px)}}
  .thumb-wrap{{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#001520}}
  .thumb-wrap img{{width:100%;height:100%;object-fit:cover}}
  .dur{{position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.8);color:#fff;
        font-size:.72rem;padding:2px 5px;border-radius:3px}}
  .info{{padding:10px 12px 12px}}
  .title{{font-size:.9rem;color:#d8f8ff;font-weight:600;line-height:1.3;
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
  .channel{{font-size:.78rem;color:#3a8a9a;margin-top:5px}}
  .hdr{{display:flex;align-items:center;gap:12px;margin-bottom:16px}}
  .logo{{color:#00d4ff;font-size:1.4rem;font-weight:700;letter-spacing:2px}}
  .search-box{{flex:1;background:#010f18;border:1px solid #0d3347;border-radius:6px;
               padding:8px 14px;color:#8ffcff;font-size:.9rem;outline:none}}
  .search-box:focus{{border-color:#00d4ff}}
</style>
</head>
<body>
<div class="hdr">
  <span class="logo">J.A.R.V.I.S</span>
  <input class="search-box" value="{query}" readonly title="Search query">
</div>
<h1>◈ {platform} Results</h1>
<p class="sub">{len(videos)} video{"s" if len(videos) != 1 else ""} found for &ldquo;{query}&rdquo; &mdash; click any card to watch</p>
<div class="grid">{cards_html}
</div>
</body>
</html>"""

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False,
        prefix="jarvis_video_", encoding="utf-8"
    )
    tmp.write(html)
    tmp.close()
    return Path(tmp.name).as_uri()


# ── YouTube trending & transcript helpers ─────────────────────────────────────

def _yt_extract_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _yt_get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        tl    = YouTubeTranscriptApi.list_transcripts(video_id)
        langs = ["en", "en-US", "en-GB", "fr", "de", "es", "pt", "it", "ja", "ko", "ar", "ru"]
        tr    = None
        try:
            tr = tl.find_manually_created_transcript(langs)
        except Exception:
            pass
        if tr is None:
            try:
                tr = tl.find_generated_transcript(langs)
            except Exception:
                for t in tl:
                    tr = t; break
        if tr is None:
            return None
        return " ".join(e["text"] for e in tr.fetch())
    except Exception as e:
        print(f"[VideoSearch] Transcript fetch failed: {e}")
        return None


def _yt_summarize(transcript: str, url: str) -> str:
    try:
        from openai import OpenAI
        cfg      = _load_config()
        groq_key = cfg.get("groq_api_key",  "").strip()
        nim_key  = cfg.get("nvidia_api_key", "").strip()
        if groq_key and groq_key not in ("", "YOUR_GROQ_KEY_HERE"):
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
            model  = cfg.get("groq_model", "llama-3.3-70b-versatile")
        elif nim_key:
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nim_key)
            model  = cfg.get("nvidia_model", "meta/llama-3.3-70b-instruct")
        else:
            return "No AI key configured for summarization."
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "You are JARVIS. Summarize the YouTube transcript concisely. "
                    "1-sentence overview then 3-5 bullet-point key takeaways. "
                    "Address the user as 'boss'."},
                {"role": "user", "content": f"Transcript:\n{transcript[:12000]}"},
            ],
            max_tokens=500, temperature=0.3,
        )
        return (resp.choices[0].message.content or "Could not summarize.").strip()
    except Exception as e:
        return f"Summarization failed: {e}"


def _yt_trending(region: str = "US", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r      = requests.get(url, headers=_HEADERS, timeout=12)
        html   = r.text
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        chans  = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        ids    = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            vid = ids[i] if i < len(ids) else ""
            results.append({
                "rank":          len(results) + 1,
                "title":         title,
                "channel":       chans[i] if i < len(chans) else "Unknown",
                "video_id":      vid,
                "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else "",
                "watch_url":     f"https://www.youtube.com/watch?v={vid}" if vid else "",
                "duration":      "",
                "platform":      "YouTube",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[VideoSearch] YT trending failed: {e}")
        return []


# ── Platform search URL builders ──────────────────────────────────────────────

def _platform_search_url(platform: str, query: str) -> str:
    q = quote_plus(query)
    urls = {
        "youtube":     f"https://www.youtube.com/results?search_query={q}&sp={_YT_VIDEO_FILTER}",
        "tiktok":      f"https://www.tiktok.com/search?q={q}",
        "instagram":   f"https://www.instagram.com/explore/search/keyword/?q={q}",
        "twitter":     f"https://twitter.com/search?q={q}&f=video",
        "x":           f"https://twitter.com/search?q={q}&f=video",
        "reddit":      f"https://www.reddit.com/search/?q={q}&type=link",
        "facebook":    f"https://www.facebook.com/search/videos/?q={q}",
        "twitch":      f"https://www.twitch.tv/search?term={q}",
        "vimeo":       f"https://vimeo.com/search?q={q}",
        "dailymotion": f"https://www.dailymotion.com/search/{q}",
        "rumble":      f"https://rumble.com/search/video?q={q}",
    }
    return urls.get(platform.lower(), urls["youtube"])


_PLATFORM_NAMES = {
    "tiktok": "TikTok", "instagram": "Instagram", "twitter": "Twitter/X",
    "x": "Twitter/X", "reddit": "Reddit", "facebook": "Facebook",
    "twitch": "Twitch", "vimeo": "Vimeo", "dailymotion": "Dailymotion",
    "rumble": "Rumble", "youtube": "YouTube",
}


# ── Action handlers ───────────────────────────────────────────────────────────

def _handle_play(params: dict, player) -> str:
    query    = params.get("query", "").strip()
    platform = params.get("platform", "youtube").lower().strip()

    if not query:
        return "Please tell me what you'd like to watch, boss."

    if player:
        player.write_log(f"[VideoSearch] {platform}: {query}")

    if platform == "youtube":
        # Scrape multiple results → build HTML page → open in browser
        print(f"[VideoSearch] Scraping YouTube for: {query!r}")
        videos = _yt_scrape_videos(query, max_results=8)
        print(f"[VideoSearch] Scrape returned {len(videos)} video(s)")

        if videos:
            # If only 1 result — open it directly; otherwise show the results page
            if len(videos) == 1:
                print(f"[VideoSearch] Single result — opening directly: {videos[0]['watch_url']}")
                _open_url(videos[0]["watch_url"])
                return f"Playing '{videos[0]['title']}' on YouTube, boss."

            print(f"[VideoSearch] Building HTML results page for {len(videos)} videos")
            page_url = _build_results_page(query, videos, platform="YouTube")
            print(f"[VideoSearch] HTML page: {page_url}")
            _open_url(page_url)
            return (
                f"Found {len(videos)} YouTube videos for '{query}', boss. "
                f"Results are displayed in your browser — click any card to watch."
            )

        # Fallback: open YouTube search page directly
        print(f"[VideoSearch] Scrape returned nothing — opening YouTube search page")
        fallback = _platform_search_url("youtube", query)
        _open_url(fallback)
        return f"Opened YouTube search for '{query}' in your browser, boss."

    # Non-YouTube platforms — open their search page directly
    url  = _platform_search_url(platform, query)
    name = _PLATFORM_NAMES.get(platform, platform.capitalize())
    _open_url(url)
    return f"Opened {name} search for '{query}' in your browser, boss."


def _handle_search_all(params: dict, player) -> str:
    """
    Search across multiple platforms.
    If a single platform is specified, redirect to _handle_play for that platform only.
    Only opens multiple platforms when no specific platform was given.
    """
    query     = params.get("query", "").strip()
    platform  = params.get("platform", "").lower().strip()
    platforms = params.get("platforms", [])

    if not query:
        return "Please provide a search query, boss."

    # If a single specific platform was given, redirect to play (single platform)
    if platform and platform not in ("all", ""):
        print(f"[VideoSearch] search_all redirected to play — platform={platform!r}")
        return _handle_play(params, player)

    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",")]

    # No platform specified — search across defaults
    if not platforms:
        platforms = ["youtube", "tiktok", "instagram", "twitter", "reddit"]

    # Open YouTube with HTML results page first
    if "youtube" in platforms:
        videos = _yt_scrape_videos(query, max_results=6)
        if videos:
            page_url = _build_results_page(query, videos, "YouTube")
            _open_url(page_url)
        else:
            _open_url(_platform_search_url("youtube", query))

    # Open remaining platforms (max 3 extra tabs to avoid flooding browser)
    others = [p for p in platforms if p != "youtube"]
    for p in others[:3]:
        _open_url(_platform_search_url(p, query))
        time.sleep(0.4)

    names = ", ".join(_PLATFORM_NAMES.get(p, p.capitalize()) for p in platforms)
    return f"Searching '{query}' across {names} in your browser, boss."


def _handle_summarize(params: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"
    url = params.get("url", "").strip()
    if not url:
        return "Please provide a YouTube video URL to summarize, boss."
    if "youtube.com" not in url and "youtu.be" not in url:
        return "Summarization currently supports YouTube links only, boss."
    video_id = _yt_extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, boss."
    if player:
        player.write_log(f"[VideoSearch] Summarizing: {url}")
    if speak:
        speak("Fetching transcript now, boss. One moment.")
    transcript = _yt_get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, boss."
    if speak:
        speak("Generating summary now, boss.")
    summary = _yt_summarize(transcript, url)
    if params.get("save", False):
        from datetime import datetime
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.home() / "Desktop" / f"video_summary_{ts}.txt"
        path.write_text(f"JARVIS Video Summary\nURL: {url}\n\n{summary}", encoding="utf-8")
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except Exception:
            pass
        return f"Summary saved to Desktop: {path.name}\n\n{summary}"
    return summary


def _handle_trending(params: dict, player, speak) -> str:
    region   = params.get("region", "US").upper()
    platform = params.get("platform", "youtube").lower()

    if platform != "youtube":
        trending_urls = {
            "tiktok":    "https://www.tiktok.com/trending",
            "instagram": "https://www.instagram.com/explore/",
            "twitter":   "https://twitter.com/explore/tabs/trending",
            "reddit":    "https://www.reddit.com/r/videos/top/?t=day",
        }
        url = trending_urls.get(platform, f"https://www.youtube.com/feed/trending?gl={region}")
        _open_url(url)
        return f"Opened {_PLATFORM_NAMES.get(platform, platform)} trending in your browser, boss."

    if player:
        player.write_log(f"[VideoSearch] Trending: {region}")

    trending = _yt_trending(region=region, max_results=8)
    if not trending:
        url = f"https://www.youtube.com/feed/trending?gl={region}"
        _open_url(url)
        return f"Could not scrape trending — opened YouTube trending for {region} in browser, boss."

    # Build results page from trending videos
    page_url = _build_results_page(f"Trending in {region}", trending, "YouTube Trending")
    _open_url(page_url)

    result = f"Top trending on YouTube ({region}):\n"
    result += "\n".join(f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending[:5])

    if speak:
        top3   = trending[:3]
        spoken = "Top trending videos: " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result


def _handle_open_channel(params: dict, player) -> str:
    channel  = params.get("channel", "").strip()
    platform = params.get("platform", "youtube").lower()
    if not channel:
        return "Please provide a channel name, boss."
    urls = {
        "youtube":   f"https://www.youtube.com/@{quote_plus(channel)}",
        "tiktok":    f"https://www.tiktok.com/@{quote_plus(channel)}",
        "instagram": f"https://www.instagram.com/{quote_plus(channel)}/",
        "twitter":   f"https://twitter.com/{quote_plus(channel)}",
        "twitch":    f"https://www.twitch.tv/{quote_plus(channel)}",
    }
    url = urls.get(platform, urls["youtube"])
    _open_url(url)
    return f"Opened {_PLATFORM_NAMES.get(platform, platform)} channel '{channel}' in your browser, boss."


# ── Public entry point ────────────────────────────────────────────────────────

def video_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Multi-platform video search — results displayed in the user's real browser.

    parameters:
        action   : play | search_all | summarize | trending | open_channel
        query    : search term
        platform : youtube | tiktok | instagram | twitter | reddit |
                   facebook | twitch | vimeo | dailymotion | rumble
        platforms: list for search_all
        url      : YouTube URL for summarize
        region   : region code for trending (US, NG, GB, etc.)
        channel  : username for open_channel
        save     : save summary to Desktop
    """
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[VideoSearch] Action: {action}")
    print(f"[VideoSearch] Action: {action}  Params: {params}")

    try:
        if action == "play":
            return _handle_play(params, player) or "Done."
        elif action == "search_all":
            # If a single platform was specified, treat as play — not multi-platform search
            if params.get("platform", "").strip().lower() not in ("", "all"):
                return _handle_play(params, player) or "Done."
            return _handle_search_all(params, player) or "Done."
        elif action == "summarize":
            return _handle_summarize(params, player, speak) or "Done."
        elif action == "trending":
            return _handle_trending(params, player, speak) or "Done."
        elif action in ("open_channel", "channel"):
            return _handle_open_channel(params, player) or "Done."
        else:
            params["query"] = params.get("query", "") or action
            return _handle_play(params, player) or "Done."
    except Exception as e:
        print(f"[VideoSearch] Error in {action}: {e}")
        return f"Video search failed, boss: {e}"
