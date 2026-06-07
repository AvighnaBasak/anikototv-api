# Anikoto → MegaPlay Reverse Engineering: Full Recon Summary

> **Purpose:** Curiosity-driven reverse engineering of HiAnime's new frontend (Anikoto) to map the full video delivery chain down to the CDN. No production use — purely exploratory.

> **STATUS: CHAIN FULLY CRACKED (2026-06-07)** — HLS stream is directly accessible. See Section 11.

---

## 1. Target Overview

| Property | Value |
|---|---|
| Frontend site | `https://anikototv.to` |
| Anime tested | *Danchi-Mura no Deviant-san* (slug: `doku-danchi-deviant-s-apartment-complex-shvpb`) |
| Episode tested | Episode 9 |
| Episode page URL | `https://anikototv.to/doku-danchi-deviant-s-apartment-complex-shvpb/ep-9` |
| Anime ID | `8748` |
| Anikoto is a clone/successor of | HiAnime / Zoro.to |

---

## 2. The Full Embed Chain

```
anikototv.to (frontend)
    │
    ├── GET /8748  (anime page)
    ├── GET /list?type=anime&id=8748
    ├── GET /getSources?id=176774&id=176774   ← source resolver
    │
    └──▶ megaplay.buzz (embed host)
             │
             ├── GET /stream/s-2/898515/sub   ← embed page
             │
             └──▶ lostproject.club (CDN)
                      │
                      ├── /anime/.../subtitles/....vtt   ← subtitle files
                      └── [HLS .m3u8 stream]             ← video stream
```

---

## 3. Anikoto API Endpoints Identified

### 3.1 Source Resolver

```
GET https://anikototv.to/getSources?id=176774&id=176774
```

**Response (JSON):**
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

### 3.2 Server Resolver (obfuscated token)

```
GET https://anikototv.to/server?get=MTF1dkFtaW9BRTZPbzJJREIFZUZrOWdjeldjOERLaWNMMXFNbVB3WUJqK1JNM1ByWFJ6MlpicG5p...
```

The `get` parameter is a **base64-encoded token** that Anikoto's backend decodes to resolve the server. Tokens are session-scoped and expire.

**Payload tab shows:**
```
get = MTF1dkFtaW9BRTZPbzJJREIFZUZrOWdjeldjOERLaWNN...Y0tGMmI4eXA0Y0xkVGRpN3Z6cUxpTXJvbUE5UEQ=
```

### 3.3 Other Observed Requests

| Endpoint | Purpose |
|---|---|
| `/8748` | Anime detail page |
| `/8748?vrf=` | VRF-validated anime page |
| `/list?servers=blpHT1JudGsrVW9vQXRGREZtWVhrR2xUYUdk2V...` | Server list for episode |
| `/list?type=anime&id=8748` | Anime metadata |
| `/1780252803` | Unknown (possibly analytics/session) |
| `/domains?h=2026060105` | Domain list fetch (ad routing, base64 encoded) |
| `dump.mewcdn.online` | Analytics/telemetry endpoint (3rd party) |

---

## 4. MegaPlay Embed — Full Analysis

### 4.1 Embed URL

```
https://megaplay.buzz/stream/s-2/898515/sub
```

| Segment | Value | Meaning |
|---|---|---|
| `s-2` | Server 2 | Fallback server index |
| `898515` | Episode real ID | Stable per episode, not session-scoped |
| `sub` | Track type | Subbed variant (vs `dub`) |

### 4.2 Player HTML (retrieved via curl + `--write-pages`)

```html
<div class="fix-area" id="megaplay-player"
    data-id="176774"
    data-realid="898515"
    data-mediaid="8737"
    data-fileversion="0">
```

**Inline JS settings object:**
```javascript
const settings = {
    time: 0,
    autoPlay: "1",
    playOriginalAudio: "1",
    autoSkipIntro: "0",
    vast: 0,
    base_url: 'https://megaplay.buzz/',
    domain2_url: 'Array',
    type: 'sub',
    cid: '4445',
    cidu: '6a1c81b930f90',
};
```

**JS files loaded:**
```
https://cdn.jsdelivr.net/gh/itspro-dev/project_files@master/jw/hls.js?v=0.2
https://megaplay.buzz/lib/app.main.js?v=2.1
https://megaplay.buzz/lib/jw_player.js?s
https://code.jquery.com/jquery-3.6.0.min.js
https://megaplay.buzz/lib/e1-player.min.js?v=2.0
```

### 4.3 JW Player Config (from `jw_player.js`)

```javascript
var jwDefaults = {
    "aspectratio": "16:9",
    "autostart": false,
    "controls": true,
    "cast": { "appid": "00000000" },
    "height": 360,
    "key": "ITWMv7t88JGzI0xPwW8I0+LveiXX9SWbfdmt0ArUSyc=",
    "mute": false,
    "ph": 1,
    "pid": "aVr2lJgW",
    "playbackRateControls": true,
    "preload": "none",
    "repeat": false,
    "stretching": "uniform",
    "width": "100%",
};
```

**JW Player version:** `8.33.2`

### 4.4 app.main.js — Ad Routing Logic

```javascript
// Country-based ad routing
const premium = {US:1, GB:1, CA:1, AU:1, ...IN not listed...};
const fallback = "//la.bodegashunlike.com/rZWGaGXvSTMsnm6/113499";
const premiumAd = "//sl.linkmansclate.com/rXJ7LJ0ckEf56j05/137054";

// Domain whitelist fetched dynamically
fetch(`https://megaplay.buzz/domains?h=${cachebuster}`)
    .then(e => e.text())
    .then(e => { domains = JSON.parse(atob(e)); ... });

// Ad telemetry check
fetch("https://dump.nekostream.site/", { timeout: 2000 })
    .then(r => JSON.parse(r).country)
    .then(country => loadAd(premium[country] ? premiumAd : fallback));
```

---

## 5. The CDN Layer — lostproject.club

### 5.1 Subtitle URL Structure

```
https://1oe.lostproject.club/anime/
    {hash1}/          ← 08a060a61b90a099b277ce6a1982dfbb
    {hash2}/          ← bc7549676a145f0c0f16f95d3172aa4b
    subtitles/
    {filehash}_{episodeid}_sub_{lang}-{index}.vtt
```

**Example:**
```
https://1oe.lostproject.club/anime/08a060a61b90a099b277ce6a1982dfbb/bc7549676a145f0c0f16f95d3172aa4b/subtitles/83a39a4e6c3b273a84e20eecbf24d040_133451_sub_eng-0.vtt
```

| Part | Value |
|---|---|
| Subdomain | `1oe` (rotating) |
| Hash 1 | `08a060a61b90a099b277ce6a1982dfbb` |
| Hash 2 | `bc7549676a145f0c0f16f95d3172aa4b` |
| File hash | `83a39a4e6c3b273a84e20eecbf24d040` |
| Episode ID | `133451` |
| Language | `eng` |

### 5.2 CDN Protection

- **Cloudflare bot protection** active on `lostproject.club`
- Blocks: raw `curl`, browser fetch with `credentials: include`, browser fetch without cookies
- Blocked IP (recorded): `2402:e280:2149:678:a08d:841e:fc96:f716` (IPv6)
- Cloudflare Ray ID at time of block: `a04bc7835a849db9`
- Requires: valid `cf_clearance` cookie + matching User-Agent from a passed JS challenge

---

## 6. e1-player.min.js — Obfuscation & DevTools Protection

### 6.1 Obfuscation Method

The file uses a **custom XOR cipher** with a key derived from the function's own `.toString()` hash:

```javascript
// Job ID: u35rkcfnk55d
let JHak;
!function() {
    const wtiqb = Array.prototype.slice.call(arguments);
    return eval("(function o7Ri(XmZ) {
        const zU1 = Xk2ub(XmZ, rKR(o7Ri.toString()));
        // XOR decrypt zU1, then eval it
    })(\"_%01%18%18...\")");
}();
```

- Key function: `rKR()` — hashes the outer function's source code via char codes
- Decrypt function: `Xk2ub()` — XOR decrypts the URL-encoded payload using the key
- Anti-tamper: if the code is modified, `rKR()` produces a different key → decryption fails → `"Error: the code has been tampered!"`

### 6.2 DevTools Detection Suite

The player runs **multiple parallel detection methods** at startup:

| Check ID | Method | What it detects |
|---|---|---|
| `wZEJb` | `toString` override counter | DevTools calling `.toString()` on functions |
| `IyHEb` | Regex `.toString()` timing | DevTools property access timing |
| `AcTzb` | `debugger` statement timing | `debugger` pause overhead (>100ms = DevTools open) |
| `MBFOb` | Worker-based detection | DevTools in separate thread |
| `YaIJb` | Symbol property override | DevTools enumeration of symbols |
| `UbVvb` | `eruda` check | Mobile DevTools (eruda library) |
| `sKprb` | `console` override | Console interception |
| `Iinqb` | Combined channel timing | Worker + timing combined check |

**On detection:**
```javascript
// Clears the DOM and redirects away
window[JHak.JrUf(316)](JHak.JrUf(28), JHak.FmPf(317));
window[JHak.dRjg(318)]();
setTimeout(() => { window[JHak.ZRPh(0)][JHak.ZRPh(8)](JHak.ZLeg(319)); }, 100);
// Resolves to: document.write(""), document.clear(), location.replace(somewhere)
```

---

## 7. What Was Tried and Why It Failed

| Attempt | Result | Why |
|---|---|---|
| Direct fetch of VTT URL | Cloudflare 403 | IP flagged, no `cf_clearance` |
| Fetch with `credentials: include` | CORS error + 403 | `Access-Control-Allow-Origin: *` incompatible with `credentials: include` |
| `yt-dlp` on megaplay embed URL | `Unsupported URL` | No megaplay extractor, page is JS-rendered |
| `yt-dlp --write-pages` | Got player HTML ✅ | But no embeds found in static HTML |
| `yt-dlp --cookies-from-browser chrome` | Cookie DB locked | Chrome was running |
| `curl /api/source/176774` | 404 | Wrong endpoint |
| `curl /api/file/176774` | 404 | Wrong endpoint |
| `curl /api/e/176774` (POST) | 404 | Wrong endpoint |
| `curl /api/e/176774?cid=4445&cidu=6a1c81b930f90` | 404 | Wrong endpoint / missing auth |
| `curl /api/player` with POST body | 404 | Wrong endpoint |
| `curl /api/e/898515` (realid) | 404 | Wrong endpoint |
| Open DevTools while player loads | Player blacks out | DevTools detection kills player |
| Open DevTools after video plays | Network log empty | Chrome clears log on DevTools open (Preserve Log not pre-set) |

---

## 8. IDs & Tokens Collected

| Name | Value | Scope |
|---|---|---|
| Anime ID | `8748` | Stable (per anime) |
| MegaPlay file ID | `176774` | Stable (per episode/server) |
| MegaPlay real ID | `898515` | Stable (per episode) |
| MegaPlay media ID | `8737` | Stable (per anime?) |
| Session client ID `cid` | `4445` | Session-scoped |
| Session client UUID `cidu` | `6a1c81b930f90` | Session-scoped |
| JW Player key | `ITWMv7t88JGzI0xPwW8I0+LveiXX9SWbfdmt0ArUSyc=` | Static (hardcoded) |
| JW Player pid | `aVr2lJgW` | Static (hardcoded) |
| Cloudflare Ray ID | `a04bc7835a849db9` | Per-block |
| Anikoto server token | `MTF1dkFtaW9BRTZPbzJJREIFZ...` (truncated) | Short-lived session token |

---

## 9. What Would Be Needed to Go Further

### Option A — Deobfuscate e1-player.min.js offline
Extract the encrypted payload string from the JS, reimplement `rKR()` and `Xk2ub()` in Python, decrypt it, and read the actual API endpoint. Estimated effort: 2–4 hours.

```python
# Rough approach
def rKR(source: str) -> str:
    Tjrb = 1414548430
    for i, ch in enumerate(source):
        Tjrb ^= (ord(ch) * (15658734 ^ 0o73567354) + ord(source[i >> 3])) ^ 1671507526
    # ... generate key string from Tjrb
    
def Xk2ub(encoded: str, key: str) -> str:
    decoded = urllib.parse.unquote(encoded)
    result = ""
    ki = 0
    for ch in decoded:
        result += chr(ord(ch) ^ ord(key[ki % len(key)]))
        ki += 1
    return result
```

### Option B — Playwright headless interception
Run the megaplay embed in a headless browser, intercept the source API network request before devtools detection fires:

```python
from playwright.async_api import async_playwright

async def get_sources(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        sources = []
        page.on("response", lambda r: sources.append(r) 
                if "megaplay.buzz/api" in r.url else None)
        
        await page.goto(url)
        await page.wait_for_timeout(5000)
        return sources
```

## 10. Summary (Original)

The Anikoto → MegaPlay → lostproject.club chain is a well-engineered 3-layer stack:

1. **Anikoto** acts as a metadata + source resolver frontend, using signed/expiring tokens to gate API access
2. **MegaPlay** is the embed host with a heavily obfuscated XOR-encrypted player, JW Player 8.33.2, and active devtools detection that prevents live network capture
3. **lostproject.club** is the actual CDN, protected by Cloudflare bot management requiring a valid `cf_clearance` cookie

The weakest link for programmatic access is the MegaPlay source API — if the endpoint can be recovered by decrypting `e1-player.min.js` offline, the rest of the chain is resolvable with proper headers. The CDN layer would still require either a persistent Cloudflare session or a TLS-fingerprint spoofer like `curl_cffi` with `impersonate="chrome124"`.

---

## 11. SOLVED — Full Chain Cracked (2026-06-07)

### 11.1 The Source API

```
GET https://megaplay.buzz/stream/getSources?id=<data-id>
```

**Minimum required headers:**
```
Referer: https://megaplay.buzz/
User-Agent: Mozilla/5.0 ... Chrome/124 ...
X-Requested-With: XMLHttpRequest
```

No cookies. No tokens. No Cloudflare bypass needed.

**Example (ep 9, server 2, `data-id` = `176774`):**

**Response:**
```json
{
  "sources": {
    "file": "https://cdn.mewstream.buzz/anime/08a060a61b90a099b277ce6a1982dfbb/bc7549676a145f0c0f16f95d3172aa4b/master.m3u8"
  },
  "tracks": [
    {
      "file": "https://1oe.lostproject.club/anime/.../83a39a4e6c3b273a84e20eecbf24d040_133451_sub_eng-0.vtt",
      "label": "English",
      "kind": "captions",
      "default": true
    }
  ],
  "t": 1,
  "intro": { "start": 0, "end": 0 },
  "outro": { "start": 0, "end": 0 },
  "server": 4
}
```

### 11.2 Stream URLs (Ep 9 — confirmed live 2026-06-07)

Video CDN is `cdn.mewstream.buzz` (different from `lostproject.club`).
**CORS: `Access-Control-Allow-Origin: *` — no browser restriction. No auth.**

| Quality | URL |
|---|---|
| Master playlist | `https://cdn.mewstream.buzz/anime/08a060a61b90a099b277ce6a1982dfbb/bc7549676a145f0c0f16f95d3172aa4b/master.m3u8` |
| 1080p | `.../index-f1.m3u8` |
| 720p | `.../index-f2.m3u8` |
| 360p | `.../index-f3.m3u8` |

**To play in browser:** paste `master.m3u8` URL into `https://hls-js.netlify.app/demo/`  
**To play with VLC:** Open Network Stream → paste the URL  
**To download with yt-dlp:**
```
yt-dlp "https://cdn.mewstream.buzz/anime/.../master.m3u8" --add-header "Referer:https://megaplay.buzz/"
```

### 11.3 Getting `data-id` from the embed page

`data-id` is in embed page HTML as an attribute of `#megaplay-player` div.  
The embed URL comes from Anikoto's `getSources` API (already documented in §3.1).

```python
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

# Step 1: get embed URL from Anikoto
ep_resp = requests.get(
    "https://anikototv.to/getSources?id=176774&id=176774",
    headers={"User-Agent": UA}
).json()
embed_url = ep_resp["result"]["url"]   # https://megaplay.buzz/stream/s-2/898515/sub

# Step 2: scrape data-id from embed page
page = requests.get(embed_url, headers={"User-Agent": UA, "Referer": "https://anikototv.to/"})
data_id = BeautifulSoup(page.text, "html.parser").select_one("#megaplay-player")["data-id"]
# e.g. "176774"

# Step 3: call the source API
sources = requests.get(
    f"https://megaplay.buzz/stream/getSources?id={data_id}",
    headers={"User-Agent": UA, "Referer": "https://megaplay.buzz/", "X-Requested-With": "XMLHttpRequest"}
).json()

m3u8_url = sources["sources"]["file"]   # direct HLS stream, no auth
print(m3u8_url)
```

### 11.4 How e1-player.min.js was cracked

1. Downloaded `https://megaplay.buzz/lib/e1-player.min.js` (173 KB)
2. Outer structure: `!function(){return someEval("(function EXIr(ndQj){BODY})(PAYLOAD)")}()`
3. The decryption logic inside EXIr: key = `HAIj(EXIr.toString())`, decrypt = XOR via `XWzk(PAYLOAD, key)`
4. **Anti-tamper:** modifying EXIr's body changes `toString()` → different key → garbage decryption → SyntaxError → player shows "tampered" and exits
5. **Bypass:** ran the unmodified EXIr inside a **Node.js `vm` sandbox** with a custom `eval` injected into the VM context that intercepts the inner `someEval(PKSj)` call and saves `PKSj` to disk before execution
6. **Result:** 19,758-char obfuscated JS blob saved to disk
7. **String table decode:** the blob contains a `UPrq[]` array of 325 strings, each XOR-encoded with key `18` → decoded to find `'stream/getSources?id='` at index 38
8. Confirmed API works with just standard browser headers — no auth tokens required

### 11.5 Correction to original recon

- Video CDN is **`cdn.mewstream.buzz`**, not `lostproject.club` (subtitles are still on `lostproject.club`)
- Cloudflare bypass is **not needed** for video — `cdn.mewstream.buzz` responds to plain HTTPS with no challenge
- The `lostproject.club` subtitles still require `cf_clearance` if fetching programmatically
