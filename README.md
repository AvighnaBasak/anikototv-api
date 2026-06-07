# Anikoto Reverse Engineering — Finding the Source API

**What this is:** Curiosity-driven reverse engineering of Anikoto (anikototv.to — HiAnime's successor) to map the full video delivery chain from the frontend down to the raw HLS stream at the CDN level. The player and proxy are tools built along the way to confirm the findings work.

**What we found:** The entire chain from any anime title or MAL ID to a playable `.m3u8` stream is fully accessible programmatically — no browser, no tokens, no Cloudflare bypass needed. Anikoto embeds MAL IDs in their episode data, giving you a clean cross-reference. The full chain:

```
anikototv.to  →  megaplay.buzz  →  cdn.mewstream.buzz (video)
                               →  lostproject.club   (subtitles)
```

**Status:** Fully cracked. Confirmed working for multiple anime and CDN stacks.

**Live demo:** Open [`demo.html`](demo.html) in your browser with `proxy.py` running locally.

---

![Demo](demo.gif)

---

## ID Database — Where the IDs Come From

**Short answer: MAL IDs.**

Every episode in Anikoto's episode list carries a `data-mal` attribute containing the MyAnimeList anime ID. These are the same IDs used by the MAL API, AniList (which syncs from MAL), and every other major anime metadata database. The confirmed mappings:

| Anime | MAL ID | Anikoto anime ID | Notes |
|---|---|---|---|
| One Piece | 21 | 1642 | `data-mal="21"` on every episode |
| Jujutsu Kaisen Season 2 | 51009 | 6542 | `data-mal="51009"` on every episode |
| Danchi-Mura no Deviant-san | 8748 (anime page) | 8748 | Coincidentally same |

**Anikoto's own internal IDs** are sequential integers assigned internally — not MAL, not AniList, not AniDB. They appear in the URL slug (e.g., `one-piece-odmau`, where `odmau` is an opaque alphanumeric identifier, and the watch page exposes `data-anime-id="1642"`).

**Episode-level IDs** are also internal (30298 for One Piece ep1, 100915 for JJK S2 ep1) and have no public database equivalent.

**Bottom line for a universal streamer:** use MAL ID → title → Anikoto search → full pipeline below. The MAL ID is embedded in every episode item, so once you have the episode list you can cross-reference any episode to any external metadata database.

---

## The Complete Programmatic Pipeline

No browser. No network tab. No manual ID hunting. 7 HTTP requests from title to m3u8.

```
Search → anime_id → episode list → server list → embed URL → data-id → m3u8
```

### Step 1 — Search for the anime slug

```
GET https://anikototv.to/ajax/anime/search?keyword=<url-encoded-title>
X-Requested-With: XMLHttpRequest
```

Response: JSON with `result.html` containing `<a href="https://anikototv.to/watch/<slug>">` links.
Pick the matching result. Slug format: `one-piece-odmau`, `jujutsu-kaisen-2nd-season-hk2c9`.

### Step 2 — Get the Anikoto anime ID

```
GET https://anikototv.to/watch/<slug>/ep-1
```

Parse `data-anime-id="<ID>"` from the HTML. This is Anikoto's internal anime ID.

```python
anime_id = re.search(r'data-anime-id="(\d+)"', page_html).group(1)
# e.g. 1642 for One Piece, 6542 for JJK S2
```

### Step 3 — Get the episode list

```
GET https://anikototv.to/ajax/episode/list/<anime_id>
X-Requested-With: XMLHttpRequest
```

Response: JSON with `result` HTML. Each episode `<a>` element carries:

```html
<a href="#"
   data-id="30298"               ← Anikoto episode ID
   data-num="1"                  ← episode number
   data-slug="1"                 ← episode slug (used by mapper API)
   data-mal="21"                 ← MAL anime ID ← cross-reference!
   data-timestamp="1778430601"   ← last-updated timestamp
   data-sub="1"                  ← has sub version
   data-dub="1"                  ← has dub version
   data-ids="cTFsbUc1WkR..."     ← encrypted server list token (used in next step)
>1</a>
```

```python
import re, json

r = requests.get(f"https://anikototv.to/ajax/episode/list/{anime_id}", ...)
episodes = re.findall(
    r'data-id="(\d+)" data-num="(\d+)" data-slug="(\d+)" data-mal="(\d+)" '
    r'data-timestamp="(\d+)".*?data-ids="([^"]+)"',
    r.json()["result"]
)
# Each tuple: (ep_id, ep_num, slug, mal_id, timestamp, data_ids)
```

### Step 4 — Get the server list for an episode

```
GET https://anikototv.to/ajax/server/list?servers=<episode_data-ids>
X-Requested-With: XMLHttpRequest
```

The `data-ids` value from step 3 is passed verbatim as the `servers=` parameter. No additional encoding needed.

Response: JSON with `result` HTML containing server list items:

```html
<li data-ep-id="30298"
    data-sv-id="e54"
    data-link-id="MTF1dkFtaW9BRTZPbzJJRElFZUZr..."  ← encrypted link token
>Vidstream-2</li>
```

Known server IDs: `e54` = Vidstream-2, `a41` = VidCloud-1. Always at least one works.

```python
sv_html = requests.get(f"https://anikototv.to/ajax/server/list?servers={data_ids}", ...).json()["result"]
link_id = re.search(r'data-type="sub".*?data-link-id="([^"]+)"', sv_html, re.DOTALL).group(1)
```

### Step 5 — Get the MegaPlay embed URL

```
GET https://anikototv.to/ajax/server?get=<data-link-id>
X-Requested-With: XMLHttpRequest
```

Response:

```json
{
  "status": 200,
  "result": {
    "url": "https://megaplay.buzz/stream/s-2/2142/sub",
    "skip_data": {
      "intro": [31, 111],
      "outro": [1376, 1447]
    }
  }
}
```

The `url` field is the MegaPlay embed URL. `skip_data` contains intro/outro timestamps in seconds.

### Step 6 — Get the MegaPlay data-id

Fetch the embed URL. The HTML contains:

```html
<div id="megaplay-player" data-id="36396" ...>
```

```python
embed_page = requests.get(embed_url, headers={"Referer": "https://anikototv.to/"}, ...)
data_id = re.search(r'data-id=["\x27](\d+)', embed_page.text).group(1)
```

### Step 7 — Get the m3u8

```
GET https://megaplay.buzz/stream/getSources?id=<data-id>
Referer: https://megaplay.buzz/
X-Requested-With: XMLHttpRequest
```

Response:

```json
{
  "sources": {
    "file": "https://cdn.mewstream.buzz/anime/<hash1>/<hash2>/master.m3u8"
  },
  "tracks": [...subtitle VTT links...],
  "intro": {"start": 31, "end": 111},
  "outro": {"start": 1376, "end": 1447}
}
```

### Complete Python snippet (all 7 steps)

```python
from curl_cffi import requests as cr
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def get_stream(title, ep_num=1, sub=True):
    HDR  = {"user-agent": UA, "referer": "https://anikototv.to/"}
    HDR2 = dict(HDR, **{"x-requested-with": "XMLHttpRequest", "accept": "application/json"})

    # 1. Search
    search = cr.get(f"https://anikototv.to/ajax/anime/search?keyword={title}",
                    headers=HDR2, impersonate="chrome124").json()
    slug = re.search(r'/watch/([^"]+)"', search["result"]["html"]).group(1)

    # 2. Anime ID
    page = cr.get(f"https://anikototv.to/watch/{slug}/ep-1", headers=HDR, impersonate="chrome124")
    anime_id = re.search(r'data-anime-id="(\d+)"', page.text).group(1)

    # 3. Episode list
    ep_list = cr.get(f"https://anikototv.to/ajax/episode/list/{anime_id}",
                     headers=HDR2, impersonate="chrome124").json()["result"]
    ep = re.search(rf'data-num="{ep_num}"[^>]*data-ids="([^"]+)"', ep_list)
    data_ids = ep.group(1)

    # 4. Server list
    sv_html = cr.get(f"https://anikototv.to/ajax/server/list?servers={data_ids}",
                     headers=HDR2, impersonate="chrome124").json()["result"]
    ep_type = "sub" if sub else "dub"
    link_id = re.search(rf'data-type="{ep_type}".*?data-link-id="([^"]+)"', sv_html, re.DOTALL).group(1)

    # 5. Embed URL
    result = cr.get(f"https://anikototv.to/ajax/server?get={link_id}",
                    headers=HDR2, impersonate="chrome124").json()["result"]
    embed_url = result["url"]
    skip = result.get("skip_data", {})

    # 6. MegaPlay data-id
    embed_page = cr.get(embed_url, headers=dict(HDR, referer="https://anikototv.to/"),
                        impersonate="chrome124")
    data_id = re.search(r'data-id=["\x27](\d+)', embed_page.text).group(1)

    # 7. m3u8
    src = cr.get(
        f"https://megaplay.buzz/stream/getSources?id={data_id}",
        headers={"user-agent": UA, "referer": "https://megaplay.buzz/",
                 "x-requested-with": "XMLHttpRequest"},
        impersonate="chrome124"
    ).json()

    return {
        "m3u8":    src["sources"]["file"],
        "intro":   src.get("intro"),
        "outro":   src.get("outro"),
        "tracks":  src.get("tracks", []),
        "mal_id":  re.search(rf'data-num="{ep_num}"[^>]*data-mal="(\d+)"', ep_list).group(1),
        "skip":    skip,
    }

result = get_stream("one piece", ep_num=1)
print(result["m3u8"])
# https://s1.streamzone1.site/anime/.../master.m3u8
```

---

## The API — Complete Reference (Original 3-Step Method)

### Step 1: Get the Anikoto Episode ID

Browse any episode on `anikototv.to`. Open DevTools → Network tab → find the request:

```
GET https://anikototv.to/getSources?id=<episode_id>
```

The number in the URL is the episode ID. Response:

```json
{
  "status": 200,
  "result": {
    "url": "https://megaplay.buzz/stream/s-2/898515/sub",
    "skip_data": {
      "intro": [0, 0],
      "outro": [0, 0]
    }
  }
}
```

The `url` field is the MegaPlay embed URL for that episode.

---

### Step 2: Get the `data-id` from the MegaPlay Embed Page

Fetch the embed URL. The HTML contains a div with a `data-id` attribute:

```html
<div class="fix-area" id="megaplay-player"
    data-id="176774"
    data-realid="898515"
    data-mediaid="8737"
    data-fileversion="0">
```

`data-id` is the ID you pass to the source API. It is stable per episode (not session-scoped).

---

### Step 3: Call the MegaPlay Source API

```
GET https://megaplay.buzz/stream/getSources?id=<data-id>
```

**Required headers:**
```
Referer: https://megaplay.buzz/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
X-Requested-With: XMLHttpRequest
```

No cookies. No tokens. No auth. No Cloudflare challenge.

**Response:**
```json
{
  "sources": {
    "file": "https://cdn.mewstream.buzz/anime/<hash1>/<hash2>/master.m3u8"
  },
  "tracks": [
    {
      "file": "https://1oe.lostproject.club/anime/.../subtitles/eng.vtt",
      "label": "English",
      "kind": "captions",
      "default": true
    }
  ],
  "intro": { "start": 31, "end": 111 },
  "outro": { "start": 1376, "end": 1447 }
}
```

- `sources.file` — direct HLS master playlist. `Access-Control-Allow-Origin: *`. No auth.
- `tracks[].file` — subtitle VTT files on `lostproject.club` (Cloudflare-protected — see CDN Notes)
- `intro` / `outro` — timestamps in seconds for skip buttons

---

### Full Python Snippet (all 3 steps)

```python
from curl_cffi import requests as cr
import re

UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HDR = {"user-agent": UA, "referer": "https://anikototv.to/"}

# Step 1: get embed URL from Anikoto
ep      = cr.get("https://anikototv.to/getSources?id=176774", headers=HDR, impersonate="chrome124").json()
emb_url = ep["result"]["url"]
# https://megaplay.buzz/stream/s-2/898515/sub

# Step 2: scrape data-id from embed page
pg      = cr.get(emb_url, headers=dict(HDR, referer="https://anikototv.to/"), impersonate="chrome124")
data_id = re.search(r'data-id=["\x27](\d+)', pg.text).group(1)
# "176774"

# Step 3: call source API
src = cr.get(
    f"https://megaplay.buzz/stream/getSources?id={data_id}",
    headers={
        "user-agent": UA,
        "referer":    "https://megaplay.buzz/",
        "x-requested-with": "XMLHttpRequest"
    },
    impersonate="chrome124"
).json()

print(src["sources"]["file"])
# https://cdn.mewstream.buzz/anime/<hash1>/<hash2>/master.m3u8
```

`curl_cffi` with `impersonate="chrome124"` replays Chrome's exact TLS handshake. Required for some CDN segment hosts that check TLS fingerprints. For the main source API call it is not strictly required but good practice.

---

### The m3u8 URL — Quality Structure

```
master.m3u8         → lists available quality playlists
  index-f1.m3u8     → 1080p
  index-f2.m3u8     → 720p
  index-f3.m3u8     → 360p
```

Quality playlists contain segment URLs. Segments use fake extensions (`.jpg`, `.html`, `.css`, `.js`) but are real MPEG-TS data (first byte `0x47`).

---

## Alternative: mapper.nekostream.site (MAL ID Direct Route)

Anikoto uses `mapper.nekostream.site` as a secondary source backend that resolves streams by MAL ID directly, without going through the episode list pipeline above. This route uses AnimePahe as the source rather than MegaPlay.

```
GET https://mapper.nekostream.site/api/mal/<MAL_ID>/<episode_slug>/<timestamp>
```

- `MAL_ID` — from `data-mal` in the episode list, or from any MAL/AniList API
- `episode_slug` — from `data-slug` in the episode list (usually just the episode number: "1", "2", "3"...)
- `timestamp` — from `data-timestamp` in the episode list (update timestamp, semi-static)

Response:

```json
{
  "Kiwi-Stream-": {
    "sub": {
      "url": "MTF1dkFtaW9BRTZPbzJJRElFZUZr..."
    },
    "dub": {
      "url": "MTF1dkFtaW9BRTZPbzJJRElFZUZr..."
    }
  },
  "Kiwi-Stream": {
    "sub": {
      "download": {
        "Kiwi-Stream-720p": "https://pahe.nekostream.site/EqmUA",
        "Kiwi-Stream-1080p": "https://pahe.nekostream.site/fmkoo"
      }
    }
  },
  "status": {
    "serves_from": "cached",
    "cache_expires_in": "1 hours 33 minutes"
  }
}
```

- `Kiwi-Stream-` → AnimePahe streaming (embed) links — the `url` is a server-encrypted token, client-side decoded
- `Kiwi-Stream` → AnimePahe download links via `pahe.nekostream.site` (short URLs → `kwik.cx` — Cloudflare protected)
- Results are cached for ~1 hour per episode

This route is how Anikoto's "Kiwi-Stream" server selection works. The MegaPlay pipeline (7-step above) is more reliable and better understood.

---

## Playing the Stream

### Option A — Browser via Proxy (recommended)

Run the local proxy (see below), then open `http://localhost:7979` in Chrome Incognito.

Paste into the input box:

- If CDN is `cdn.mewstream.buzz` — paste the path directly:
  ```
  /anime/<hash1>/<hash2>/master.m3u8
  ```

- If CDN is anything else (e.g. `s1.streamzone1.site`) — use the `/ext/` prefix:
  ```
  /ext/s1.streamzone1.site/anime/<hash1>/<hash2>/master.m3u8
  ```

**Must use Incognito.** Ad blocker extensions in regular Chrome block CDN domain requests (domains like `zapora.buzz`, `lumiflow.click` are on filter lists).

---

### Option B — VLC (no proxy needed)

```
vlc --http-referrer "https://megaplay.buzz/" "https://cdn.mewstream.buzz/anime/.../master.m3u8"
```

Or through the proxy (works for any CDN):
```
vlc "http://localhost:7979/anime/<hash1>/<hash2>/master.m3u8"
```

---

### Option C — yt-dlp download

```
yt-dlp "https://cdn.mewstream.buzz/anime/.../master.m3u8" --add-header "Referer:https://megaplay.buzz/"
```

---

### Option D — Online HLS Player (no setup)

Paste the `master.m3u8` URL into `https://hls-js.netlify.app/demo/` — works if your CDN host is not Cloudflare-protected.

---

## Running the Proxy

**Requirements:** Python 3.10+, `curl_cffi`

```
pip install curl_cffi
cd C:\_C_\Users\hianime
python proxy.py
```

Open Chrome Incognito → `http://localhost:7979`

### How the proxy works

`proxy.py` is a `ThreadingHTTPServer` on `127.0.0.1:7979`.

| Route | What it does |
|---|---|
| `GET /` | Serves the HLS.js player UI |
| `GET /anime/...` | Proxies to `cdn.mewstream.buzz` with `Referer` injected |
| `GET /ext/<host><path>` | Proxies to any CDN host with `Referer` injected |
| `OPTIONS *` | CORS preflight → 204 |

Every m3u8 response has its absolute `https://` URLs rewritten to `/ext/<host><path>` routes automatically. This means quality playlists and segment URLs from any CDN all come through the proxy transparently — you only paste the master playlist URL, everything else follows.

Uses `curl_cffi` with `impersonate="chrome124"` on every upstream request to pass CDN Cloudflare TLS fingerprint checks.

---

## Tested Episodes

| Anime | Anikoto episode ID | data-id | Video CDN | Segment CDN |
|---|---|---|---|---|
| Danchi-Mura no Deviant-san ep 9 | 176774 | 176774 | cdn.mewstream.buzz | zapora.buzz |
| Jujutsu Kaisen Season 2 ep 1 | 102662 | 15665 | cdn.mewstream.buzz | lumiflow.click |
| One Piece ep 1 | 2142 | 36396 | s1.streamzone1.site | streamzone1.site |

Note: Anikoto episode IDs are not MAL or AniList IDs — they are Anikoto-internal numeric IDs visible in network requests only.

---

## CDN Notes

- **`cdn.mewstream.buzz`** — main video CDN. No Cloudflare, CORS fully open (`Allow-Origin: *`). Direct access works.
- **Segment subdomains** — quality playlists point to subdomains like `*.zapora.buzz`, `*.zaptrix.buzz`, `*.lumiflow.click` for the actual MPEG-TS segments. Some of these enforce Cloudflare TLS fingerprint checks (JA3 matching) — `curl_cffi` `chrome124` passes these.
- **Fake segment extensions** — segments have extensions like `.jpg`, `.html`, `.css`, `.js` but are real MPEG-TS (verify: first byte is `0x47`).
- **`lostproject.club`** — subtitle CDN. Protected by Cloudflare bot management requiring a valid `cf_clearance` cookie. Not handled by this proxy. Subtitles require a browser session that has passed the JS challenge.

---

---

# BREAKDOWN

How the full Anikoto → MegaPlay → CDN chain was reverse engineered from scratch.

---

## Phase 1 — Target Identification and Surface Mapping

- **Starting point:** Anikoto (anikototv.to) is the successor/relaunch of HiAnime (zoro.to / aniwatch.to) — same codebase, new domain, same embed infrastructure.
- **Initial target:** *Danchi-Mura no Deviant-san* Episode 9 — picked as the test case, Anikoto internal ID `8748`.
- **Episode page URL:** `https://anikototv.to/doku-danchi-deviant-s-apartment-complex-shvpb/ep-9`

### Mapping the Anikoto API surface

- Opened DevTools → Network tab on the episode page.
- Observed all XHR/fetch requests during page load and player initialization.
- Key endpoints discovered:

  | Endpoint | Purpose |
  |---|---|
  | `GET /8748` | Anime detail page |
  | `GET /list?type=anime&id=8748` | Anime metadata |
  | `GET /list?servers=blpHT1JudGsrVW9v...` | Server list for episode (base64 token) |
  | `GET /getSources?id=176774` | **Source resolver — returns embed URL** |
  | `GET /server?get=MTF1dkFtaW9BRTZPbzJJREIF...` | Alternate server resolver (session-scoped base64 token) |
  | `GET /domains?h=2026060105` | Dynamic domain whitelist fetch |
  | `dump.mewcdn.online` | Analytics/telemetry endpoint |

- **`/getSources?id=<episode_id>`** was the key find — returns a JSON with the MegaPlay embed URL.

---

## Phase 2 — Analyzing the MegaPlay Embed

### The embed URL structure

- `/getSources` response: `"url": "https://megaplay.buzz/stream/s-2/898515/sub"`
- URL segments:
  - `s-2` — server index (server 2, fallback)
  - `898515` — stable episode ID (MegaPlay's internal ID, not Anikoto's)
  - `sub` — track type (subbed vs `dub`)

### The embed page HTML

- Fetched `https://megaplay.buzz/stream/s-2/898515/sub` with `curl --write-pages`.
- The HTML contains a critical div:

  ```html
  <div class="fix-area" id="megaplay-player"
      data-id="176774"
      data-realid="898515"
      data-mediaid="8737"
      data-fileversion="0">
  ```

- `data-id` (`176774`) is the ID the player JS uses to call the source API.
- `data-realid` (`898515`) matches the embed URL path segment.
- `data-mediaid` (`8737`) appears to be the anime-level ID on MegaPlay's side.

### JS files loaded by the embed

```
https://cdn.jsdelivr.net/gh/itspro-dev/project_files@master/jw/hls.js?v=0.2
https://megaplay.buzz/lib/app.main.js?v=2.1
https://megaplay.buzz/lib/jw_player.js?s
https://code.jquery.com/jquery-3.6.0.min.js
https://megaplay.buzz/lib/e1-player.min.js?v=2.0
```

### JW Player config (from `jw_player.js`)

```javascript
var jwDefaults = {
    "aspectratio": "16:9",
    "autostart": false,
    "controls": true,
    "cast": { "appid": "00000000" },
    "height": 360,
    "key": "ITWMv7t88JGzI0xPwW8I0+LveiXX9SWbfdmt0ArUSyc=",
    "pid": "aVr2lJgW",
    "playbackRateControls": true,
    "preload": "none",
    "width": "100%",
};
```

- JW Player version 8.33.2 with a hardcoded license key.
- The player license key and pid are static (hardcoded in the JS file, not session-scoped).

### Ad routing logic (`app.main.js`)

- Country-based ad routing: US, GB, CA, AU get premium ad networks; others get fallback.
- Domain whitelist fetched dynamically: `fetch("https://megaplay.buzz/domains?h=<cachebuster>")` returns base64-encoded JSON of allowed CDN domains.
- Ad telemetry: pings `dump.nekostream.site` and `dump.mewcdn.online` to determine country.

### Inline settings object in the embed HTML

```javascript
const settings = {
    time: 0,
    autoPlay: "1",
    playOriginalAudio: "1",
    autoSkipIntro: "0",
    vast: 0,
    base_url: 'https://megaplay.buzz/',
    type: 'sub',
    cid: '4445',
    cidu: '6a1c81b930f90',
};
```

- `cid` and `cidu` are session-scoped client identifiers. They look like they could be required for the API call, but ultimately are not.

---

## Phase 3 — Cracking `e1-player.min.js`

This is where the actual source API endpoint was hidden.

### The file

- URL: `https://megaplay.buzz/lib/e1-player.min.js?v=2.0`
- Size: **173 KB**
- Downloaded locally for offline analysis.

### Outer obfuscation layer

The outer structure wraps an encrypted payload in a self-invoking function:

```javascript
!function() {
    const wtiqb = Array.prototype.slice.call(arguments);
    return eval("(function EXIr(ndQj) {
        const key = HAIj(EXIr.toString());
        const decrypted = XWzk(ndQj, key);
        eval(decrypted);
    })(\"_%01%18%18...\")");
}();
```

- `EXIr` — the outer decryption wrapper function.
- `HAIj(EXIr.toString())` — derives the decryption key from `EXIr`'s own source code string.
- `XWzk(payload, key)` — XOR decrypts the URL-percent-encoded payload using the derived key.
- The encrypted payload is ~173 KB of percent-encoded garbage.

### Anti-tamper mechanism

- The key is derived directly from `EXIr.toString()`.
- If you modify a single byte of `EXIr`'s body (to add a `console.log`, for example), `toString()` changes → key changes → XOR decryption produces garbage → `eval(garbage)` throws SyntaxError.
- The player catches this and shows: `"Error: the code has been tampered!"` then redirects away.
- This means you **cannot** instrument or patch the function while running it normally.

### DevTools detection suite

The player runs 8 parallel detection methods at startup to prevent live network capture:

| Check | Method |
|---|---|
| `wZEJb` | `toString` override counter — detects DevTools calling `.toString()` on functions |
| `IyHEb` | Regex `.toString()` timing — DevTools adds latency to property access |
| `AcTzb` | `debugger` statement timing — if pause overhead >100ms, DevTools is open |
| `MBFOb` | Worker-based detection — runs check in a Web Worker thread |
| `YaIJb` | Symbol property override — detects DevTools symbol enumeration |
| `UbVvb` | `eruda` check — detects mobile DevTools library |
| `sKprb` | `console` override — intercepts console access |
| `Iinqb` | Combined channel timing — Worker + timing combined |

On detection: clears the DOM, calls `document.write("")`, then `location.replace(somewhere)` — player is gone. Opening DevTools at any point (before or after load) kills or has already killed the player.

### The bypass — Node.js `vm` sandbox

The key insight: **don't run the code in a browser, run it in an isolated Node.js `vm` context** where we control the environment.

**`e1-vm-runner.js` strategy:**

1. Read `e1-player.min.js` into a string.
2. Create a Node.js `vm` context with a custom `eval` function injected.
3. Run the outer layer (`!function(){...}()`) normally inside the VM — the outer code including `function EXIr` runs completely **unmodified**.
4. Because `EXIr` is unmodified, `EXIr.toString()` returns the exact original source → `HAIj()` produces the correct key → `XWzk()` correctly decrypts the payload.
5. When the decrypted code (`PKSj`) is about to be passed to `eval`, our injected custom eval intercepts it, saves `PKSj` to disk, then throws to stop execution.

```javascript
const vm = require('vm');
const fs = require('fs');

const src = fs.readFileSync('e1-player.min.js', 'utf8');

const context = vm.createContext({
    eval: function(code) {
        // intercept the inner eval call with the decrypted payload
        if (code.length > 1000) {
            fs.writeFileSync('e1-decrypted.js', code);
            throw new Error('CAPTURED');
        }
        return vm.runInContext(code, context);
    },
    // mock all browser globals the outer code accesses
    window: {}, document: {}, navigator: {}, location: {},
    // ...
});

try {
    vm.runInContext(src, context);
} catch(e) {
    if (e.message !== 'CAPTURED') throw e;
}
```

- Output: **`e1-decrypted.js`** — 19,758 chars of obfuscated but fully decrypted, runnable JS.
- The outer anti-tamper and DevTools detection are never triggered because we never touched `EXIr`'s body.

### Reading the decrypted blob

The decrypted JS contains `UPrq[]` — an array of **325 strings**, each XOR-encoded with a single-byte key of `18`:

```javascript
// XOR decode: char_code ^ 18 = original_char_code
"q}|qsf"      → "concat"
"wusb~sk<pghh" → "megaplay.buzz"
"uiiwi"        → "whttp" → "https"  (etc.)
```

- String at index 38: `"stream/getSources?id="` — **the source API path**

Decoded the entire 325-string table and confirmed the player calls:

```
GET https://megaplay.buzz/stream/getSources?id=<data-id>
```

with only `Referer` and `User-Agent` headers. No tokens. No session IDs. No cookies.

---

## Phase 4 — The CDN Layer

### Video CDN: `cdn.mewstream.buzz`

- `getSources` response's `sources.file` URL is on `cdn.mewstream.buzz`.
- CORS: `Access-Control-Allow-Origin: *` — fully open.
- No Cloudflare challenge on this host.
- Direct HTTPS GET works with just a `Referer: https://megaplay.buzz/` header.

### m3u8 structure

```
master.m3u8
  ├── index-f1.m3u8  (1080p)
  ├── index-f2.m3u8  (720p)
  └── index-f3.m3u8  (360p)
```

Each quality playlist references segment files (`.jpg`, `.html`, `.css`, `.js` — all real MPEG-TS, first byte `0x47`).

### Segment CDN subdomains

- Quality playlists' segment URLs point to rotating subdomains:
  - `*.zapora.buzz` (observed for Danchi-Mura)
  - `*.lumiflow.click` (observed for JJK S2)
  - `*.zaptrix.buzz` (observed in other episodes)
  - `s1.streamzone1.site` (observed for One Piece — this one serves the quality playlists too, not just segments)
- These subdomains have **Cloudflare TLS fingerprint checking** (JA3 matching).
- Node.js's built-in `https` module has a TLS fingerprint that Cloudflare flags → 403 or connection reset.
- **Fix:** Python `curl_cffi` with `impersonate="chrome124"` replays Chrome's exact BoringSSL TLS handshake → all segment CDN hosts return 200.

### Subtitle CDN: `lostproject.club`

- Subtitle URL structure:
  ```
  https://<subdomain>.lostproject.club/anime/<hash1>/<hash2>/subtitles/<filehash>_<episodeid>_sub_<lang>-<index>.vtt
  ```
- This host has full Cloudflare bot management — requires a valid `cf_clearance` cookie from a passed JS challenge.
- Not handled by the proxy. Subtitles require a real browser session.

---

## Phase 5 — Making It Work in Chrome

### The problem: CORS + CDN blocking in a plain browser

- Browser fetches to CDN directly fail: CORS issues and Cloudflare fingerprint blocking.
- Even with CORS open on the video CDN, the segment CDN subdomains block non-Chrome TLS fingerprints.
- The browser itself has a Chrome TLS fingerprint but ad blocker extensions intercept CDN domains before the request leaves Chrome.

### The solution: local proxy

Built `proxy.py` — Python `ThreadingHTTPServer` acting as a transparent HLS proxy:

**m3u8 URL rewriting:**
- When a m3u8 file is fetched upstream, all absolute `https://` URLs in the response body are rewritten to `http://localhost:7979/ext/<host><path>`.
- This means Chrome never directly contacts CDN hosts — all requests go through `localhost:7979` first.
- The proxy makes the upstream request with `curl_cffi` Chrome impersonation and the correct `Referer` header, then forwards the response to Chrome.

**Why Chrome Incognito:**
- Ad blocker extensions in regular Chrome recognize CDN domain names (`zapora.buzz`, `lumiflow.click`, etc.) and block the requests to `localhost:7979/ext/...` based on hostname pattern matching in filter lists.
- Incognito mode doesn't load extensions by default → no blocking.

**Why `Content-Length` matters:**
- Python `BaseHTTPRequestHandler` without an explicit `Content-Length` header closes the socket before the body is fully transmitted in some cases.
- Chrome received 0-byte bodies for segment requests until explicit `Content-Length: <len>` was added to every response.

**Threading:**
- `ThreadingMixIn` — each request gets its own thread, preventing one slow CDN segment from blocking other in-flight requests.
- `daemon_threads = True` — worker threads die automatically when the main thread exits (Ctrl-C).

---

## Phase 6 — Confirmation (3 Anime, 3 CDN Stacks)

### Test 1 — Danchi-Mura no Deviant-san Episode 9

- Anikoto ID: `176774`
- data-id: `176774` (same in this case)
- Video CDN: `cdn.mewstream.buzz`
- Segment CDN: `R7sN.zapora.buzz` (rotating subdomain prefix)
- Proxy route: `/anime/<hash1>/<hash2>/master.m3u8`
- Result: ✓ Plays in Chrome Incognito via proxy

### Test 2 — Jujutsu Kaisen Season 2 Episode 1

- Anikoto embed URL: `https://megaplay.buzz/stream/s-2/102662/sub`
- data-id: `15665` (different from embed URL's `102662`)
- Video CDN: `cdn.mewstream.buzz`
- Segment CDN: `b9Zj.lumiflow.click`
- Proxy route: `/anime/<hash1>/<hash2>/master.m3u8`
- Result: ✓ Plays in Chrome Incognito via proxy

### Test 3 — One Piece Episode 1

- Anikoto embed URL: `https://megaplay.buzz/stream/s-2/2142/sub`
- data-id: `36396`
- Video CDN: `s1.streamzone1.site` (different CDN stack entirely)
- Segment CDN: `s1.streamzone1.site` (same host serves both playlists and segments)
- Proxy route: `/ext/s1.streamzone1.site/anime/<hash1>/<hash2>/master.m3u8` (must use `/ext/` because host differs from `cdn.mewstream.buzz`)
- Result: ✓ Plays in Chrome Incognito via proxy

---

## Phase 7 — ID Database Investigation and Complete Programmatic Pipeline

### The question

After confirming playback worked, the next question was: where do the Anikoto episode IDs come from, and can anyone use a standard anime ID (MAL, AniList) to find and stream episodes?

### Finding the episode list API

- Fetched the One Piece watch page → found `data-anime-id="1642"` in the HTML.
- Tried known HiAnime AJAX patterns → found `/ajax/episode/list/<anime_id>` returns 200 with episode data.
- One Piece anime ID on Anikoto: `1642`. JJK S2: `6542`. These are Anikoto-internal sequential IDs, NOT MAL.

### MAL IDs found embedded in the episode list

Each `<a>` item in the episode list HTML has a `data-mal` attribute:
```html
<a data-id="30298" data-num="1" data-slug="1" data-mal="21" data-timestamp="1778430601"
   data-sub="1" data-dub="1" data-ids="cTFsbUc1WkRE...">1</a>
```
- `data-mal="21"` — One Piece's MAL ID. Confirmed: all 1164 One Piece episodes have this.
- `data-mal="51009"` — JJK Season 2's MAL ID. Same pattern.
- **Anikoto stores MAL IDs natively** as cross-references for every episode.

### The mapper.nekostream.site discovery

Found `mapper.js` in the watch page script sources. Its content revealed:
```javascript
var api = "https://mapper.nekostream.site/api/mal/";

function mapper(e, a) {
    var d = $("ul.ep-range li > a.active").data("mal");        // MAL ID
    var r = $("ul.ep-range li > a.active").data("slug");       // episode slug
    var i = $("ul.ep-range li > a.active").data("timestamp");  // timestamp
    
    var l = api + d + "/" + r + "/" + i;
    $.ajax({url: l, ...})  // calls mapper.nekostream.site/api/mal/<MAL>/<slug>/<timestamp>
}
```
- This is how Anikoto adds the "Kiwi-Stream" (AnimePahe) server option to its server list.
- The mapper API works publicly: `GET https://mapper.nekostream.site/api/mal/21/1/1778430601` returns AnimePahe stream data for One Piece ep1.
- Confirmed: `data-mal` is the input, the mapper is driven entirely by MAL ID.

### Finding the complete server loading pipeline

From `main.js`, found the full list of relevant AJAX endpoints:
- `"ajax/server/list?servers="` — loads server list for an episode
- `"ajax/server?get="` — resolves a server link to an embed URL
- `"ajax/episode/list/"` — episode list (already found)

Key chain:
- Episode `data-ids` → `ajax/server/list?servers=<data-ids>` → server items with `data-link-id`
- Server `data-link-id` → `ajax/server?get=<link-id>` → MegaPlay embed URL

### Confirmed: data-ids is the server list token

- `GET https://anikototv.to/ajax/server/list?servers=<episode_data-ids>` → 200, returns:
  ```html
  <li data-ep-id="30298" data-sv-id="e54" data-link-id="MTF1dkFtaW9BRTZPbzJJRElFZU...">Vidstream-2</li>
  <li data-ep-id="30298" data-sv-id="a41" data-link-id="MTF1dkFtaW9BRTZPbzJJRElFZU...">VidCloud-1</li>
  ```
- No VRF, no session token required — `data-ids` from the episode list is sufficient.

### Confirmed: ajax/server?get= returns the embed URL

- `GET https://anikototv.to/ajax/server?get=<link-id>` → 200:
  ```json
  {"status":200,"result":{"url":"https://megaplay.buzz/stream/s-2/2142/sub","skip_data":{"intro":[31,111],"outro":[1376,1447]}}}
  ```
- For One Piece ep1: embed URL `s-2/2142/sub` — **same ID (2142) previously captured manually from Network tab**.
- For JJK S2 ep1: embed URL `s-2/102662/sub` — **same ID (102662) previously captured manually**.
- This confirms the full pipeline is reproducible without any browser session.

### Full end-to-end test (One Piece ep1)

Ran all 7 steps programmatically:
- anime_id: `1642`
- ep1 data-ids → Vidstream-2 link-id → embed URL `megaplay.buzz/stream/s-2/2142/sub`
- MegaPlay data-id: `36396`
- m3u8: `https://s1.streamzone1.site/anime/f899139df5e1059396431415e770c6dd/61b87186ab260d05003427e16ccf5657/master.m3u8`
- Intro: 31–111s, Outro: 1376–1447s
- Subtitle track: English → `lostproject.club` (Cloudflare-protected, as noted)

---

## Key IDs and Tokens Reference

| Name | Example Value | Scope |
|---|---|---|
| MAL anime ID | `21` (One Piece), `51009` (JJK S2) | Stable, standard (from MyAnimeList) |
| Anikoto anime ID | `1642` (One Piece), `6542` (JJK S2) | Stable, Anikoto-internal |
| Anikoto episode `data-id` | `30298` (OP ep1), `100915` (JJK ep1) | Stable, Anikoto-internal |
| Anikoto episode `data-ids` | `cTFsbUc1WkRE...` (base64) | Stable — pass to `/ajax/server/list?servers=` |
| Anikoto server `data-link-id` | `MTF1dkFtaW9BRTZPbzJJRElFZUZr...` | Stable — pass to `/ajax/server?get=` |
| MegaPlay embed path ID | `2142` (OP ep1), `102662` (JJK ep1) | Stable per episode |
| MegaPlay `data-id` | `36396` (OP ep1), `15665` (JJK ep1) | Stable per episode (pass to MegaPlay getSources) |
| MegaPlay `data-mediaid` | `8737` | Stable per anime |
| JW Player key | `ITWMv7t88JGzI0xPwW8I0+LveiXX9SWbfdmt0ArUSyc=` | Static (hardcoded) |
| JW Player pid | `aVr2lJgW` | Static (hardcoded) |
| Session `cid` / `cidu` | `4445` / `6a1c81b930f90` | Session-scoped, not needed |

---

## Files in This Repo

| File | What it is |
|---|---|
| `proxy.py` | Python HLS proxy server — run this, then open Chrome Incognito at `http://localhost:7979` |
| `e1-vm-runner.js` | Node.js vm sandbox that cracked `e1-player.min.js` — runs outer decryption layer unmodified, intercepts and saves inner decrypted payload |
| `e1-decrypted.js` | 19,758-char decrypted inner payload of `e1-player.min.js` — contains `UPrq[]` string table with the source API endpoint |
| `megaplay-recon.md` | Original recon document — full chain mapping, all API endpoints, all IDs/tokens, pre-crack analysis |

### Anikoto API endpoints summary

| Endpoint | Purpose |
|---|---|
| `GET /ajax/anime/search?keyword=<title>` | Search for anime by title — returns HTML with watch page slugs |
| `GET /watch/<slug>/ep-1` | Anime watch page — contains `data-anime-id` |
| `GET /ajax/episode/list/<anime_id>` | Full episode list — returns HTML with `data-id`, `data-num`, `data-slug`, `data-mal`, `data-timestamp`, `data-ids` per episode |
| `GET /ajax/server/list?servers=<data-ids>` | Server list for an episode — returns HTML with `data-link-id` per server |
| `GET /ajax/server?get=<data-link-id>` | Resolve server to embed URL — returns `{"result":{"url":"https://megaplay.buzz/stream/s-2/<id>/sub",...}}` |
| `GET https://megaplay.buzz/stream/getSources?id=<data-id>` | MegaPlay source — returns m3u8 URL, subtitle tracks, intro/outro timestamps |
| `GET https://mapper.nekostream.site/api/mal/<MAL>/<slug>/<ts>` | AnimePahe alternative streams by MAL ID |
