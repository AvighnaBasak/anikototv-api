# python proxy.py  →  open http://localhost:7979 in Chrome Incognito
# Full-stack anime proxy: search → episode list → HLS stream via curl_cffi Chrome impersonation

import re, urllib.parse, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from curl_cffi import requests as cr

PORT   = 7979
CHROME = "chrome124"
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HDR_ANI  = {"user-agent": UA, "referer": "https://anikototv.to/"}
HDR_AJAX = dict(HDR_ANI, **{"x-requested-with": "XMLHttpRequest", "accept": "application/json"})
HDR_MP   = {"user-agent": UA, "referer": "https://megaplay.buzz/", "x-requested-with": "XMLHttpRequest"}
HDR_CDN  = {
    "referer": "https://megaplay.buzz/", "origin": "https://megaplay.buzz",
    "user-agent": UA, "accept": "*/*", "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "identity",
    "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "cross-site",
}


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

def api_search(q):
    steps = []
    try:
        url = f"https://anikototv.to/ajax/anime/search?keyword={urllib.parse.quote(q)}"
        steps.append({"n": 1, "label": "Search anikototv.to", "url": url})
        r = cr.get(url, headers=HDR_AJAX, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r.status_code

        data   = r.json()
        result = data.get("result", {})
        html   = result.get("html", "") if isinstance(result, dict) else (result or "")
        steps[-1]["snippet"] = html[:250]

        results = []
        seen    = set()
        for m in re.finditer(r'href="(?:https://anikototv\.to)?/watch/([^"/\s]+)"', html):
            slug = m.group(1).strip("/")
            if not slug or slug in seen:
                continue
            seen.add(slug)

            ctx = html[max(0, m.start() - 50): min(len(html), m.end() + 700)]

            img_m = (re.search(r'data-src="(https?://[^"]+)"', ctx) or
                     re.search(r'src="(https?://[^"]+\.(jpg|jpeg|png|webp)[^"]*)"', ctx, re.I))
            img = img_m.group(1) if img_m else ""

            title_m = (re.search(r'alt="([^"]{2,80})"', ctx) or
                       re.search(r'<h[23][^>]*>([^<]{2,80})</h[23]>', ctx) or
                       re.search(r'class="[^"]*(?:title|name)[^"]*"[^>]*>([^<]{2,80})<', ctx))
            title = title_m.group(1).strip() if title_m else slug.replace("-", " ").title()

            results.append({"slug": slug, "title": title, "img": img})

        return {"ok": True, "results": results, "steps": steps}
    except Exception as e:
        if steps: steps[-1]["error"] = str(e)
        return {"ok": False, "results": [], "steps": steps, "error": str(e)}


def api_episodes(slug):
    steps = []
    try:
        url1 = f"https://anikototv.to/watch/{slug}/ep-1"
        steps.append({"n": 1, "label": "Fetch watch page → data-anime-id", "url": url1})
        r1 = cr.get(url1, headers=HDR_ANI, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r1.status_code

        m = re.search(r'data-anime-id="(\d+)"', r1.text)
        if not m:
            raise ValueError("data-anime-id not found in page HTML")
        anime_id = m.group(1)
        steps[-1]["result"] = f"anime_id = {anime_id}"

        url2 = f"https://anikototv.to/ajax/episode/list/{anime_id}"
        steps.append({"n": 2, "label": "Fetch episode list", "url": url2})
        r2 = cr.get(url2, headers=HDR_AJAX, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r2.status_code
        ep_html = r2.json()["result"]
        steps[-1]["snippet"] = ep_html[:300]

        episodes = []
        for m in re.finditer(
            r'data-id="(\d+)"\s+data-num="(\d+)"\s+data-slug="(\d+)"\s+data-mal="(\d+)"\s+'
            r'data-timestamp="(\d+)"[^>]*data-ids="([^"]+)"',
            ep_html
        ):
            ep_id, num, ep_slug, mal, ts, data_ids = m.groups()
            frag_m = re.search(
                rf'data-id="{ep_id}"[^>]*data-sub="(\d)"[^>]*data-dub="(\d)"', ep_html
            )
            has_sub = frag_m.group(1) == "1" if frag_m else True
            has_dub = frag_m.group(2) == "1" if frag_m else False
            episodes.append({
                "id": ep_id, "num": int(num), "slug": ep_slug,
                "mal": mal, "ts": ts, "data_ids": data_ids,
                "has_sub": has_sub, "has_dub": has_dub,
            })

        steps[-1]["result"] = f"{len(episodes)} episode(s) parsed"
        return {"ok": True, "anime_id": anime_id, "episodes": episodes, "steps": steps}
    except Exception as e:
        if steps: steps[-1]["error"] = str(e)
        return {"ok": False, "episodes": [], "steps": steps, "error": str(e)}


def api_stream(data_ids, ep_type="sub"):
    steps = []
    try:
        url1 = f"https://anikototv.to/ajax/server/list?servers={data_ids}"
        steps.append({"n": 1, "label": "Get server list", "url": url1})
        r1 = cr.get(url1, headers=HDR_AJAX, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r1.status_code
        sv_html = r1.json()["result"]
        steps[-1]["snippet"] = sv_html[:350]

        lm = re.search(
            rf'data-type="{ep_type}".*?data-link-id="([^"]+)"', sv_html, re.DOTALL
        )
        if not lm:
            raise ValueError(f"No {ep_type} server found in server list")
        link_id = lm.group(1)
        nm = re.search(rf'data-link-id="{re.escape(link_id)}"[^>]*>\s*([^<]+)', sv_html)
        sv_name = nm.group(1).strip() if nm else "unknown"
        steps[-1]["result"] = f'server="{sv_name}"  link_id={link_id[:50]}…'

        url2 = f"https://anikototv.to/ajax/server?get={link_id}"
        steps.append({"n": 2, "label": "Resolve embed URL", "url": url2})
        r2 = cr.get(url2, headers=HDR_AJAX, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r2.status_code
        res2      = r2.json()["result"]
        embed_url = res2["url"]
        skip      = res2.get("skip_data", {})
        steps[-1]["result"] = f"embed_url={embed_url}"

        steps.append({"n": 3, "label": "Fetch MegaPlay embed → data-id", "url": embed_url})
        r3 = cr.get(embed_url, headers=dict(HDR_ANI, referer="https://anikototv.to/"),
                    impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r3.status_code
        dm = re.search(r'data-id=["\x27](\d+)', r3.text)
        if not dm:
            raise ValueError("data-id not found in MegaPlay embed page")
        data_id = dm.group(1)
        steps[-1]["result"] = f"data_id={data_id}"

        url4 = f"https://megaplay.buzz/stream/getSources?id={data_id}"
        steps.append({"n": 4, "label": "MegaPlay getSources → m3u8", "url": url4})
        r4 = cr.get(url4, headers=HDR_MP, impersonate=CHROME, timeout=15)
        steps[-1]["status"] = r4.status_code
        src      = r4.json()
        m3u8_raw = src["sources"]["file"]
        steps[-1]["result"] = f"m3u8={m3u8_raw}"

        mp = re.match(r'https?://([^/]+)(/.+)', m3u8_raw)
        m3u8_proxy = f"/ext/{mp.group(1)}{mp.group(2)}" if mp else m3u8_raw

        intro = src.get("intro")
        outro = src.get("outro")
        if not intro and skip.get("intro"):
            intro = {"start": skip["intro"][0], "end": skip["intro"][1]}
        if not outro and skip.get("outro"):
            outro = {"start": skip["outro"][0], "end": skip["outro"][1]}

        return {
            "ok": True, "m3u8": m3u8_proxy, "m3u8_raw": m3u8_raw,
            "intro": intro, "outro": outro, "tracks": src.get("tracks", []),
            "steps": steps,
        }
    except Exception as e:
        if steps: steps[-1]["error"] = str(e)
        return {"ok": False, "steps": steps, "error": str(e)}


# ---------------------------------------------------------------------------
# HLS proxy helpers
# ---------------------------------------------------------------------------

def rewrite_m3u8(text):
    return re.sub(
        r'https?://([^/\s]+)(/[^\s]*)',
        lambda m: f'http://localhost:{PORT}/ext/{m.group(1)}{m.group(2)}',
        text
    )


def upstream_get(host, path):
    return cr.get(f"https://{host}{path}", headers=HDR_CDN, impersonate=CHROME, timeout=30)


# ---------------------------------------------------------------------------
# Player HTML — all dynamic content built with DOM methods (no innerHTML+data)
# ---------------------------------------------------------------------------

PLAYER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AniStream</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest/dist/hls.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#09090f;color:#e2e8f0;font-family:system-ui,sans-serif;height:100vh;overflow:hidden;display:flex;flex-direction:column}
.hdr{background:#111827;border-bottom:1px solid #1f2937;padding:12px 20px;display:flex;align-items:center;gap:14px;flex-shrink:0}
.logo{font-size:1.1rem;font-weight:700;color:#818cf8;white-space:nowrap}
.sw{flex:1;max-width:520px;display:flex;gap:8px}
.sw input{flex:1;padding:9px 13px;border-radius:6px;border:1px solid #374151;background:#1f2937;color:#e2e8f0;font-size:.875rem;outline:none;transition:border-color .15s}
.sw input:focus{border-color:#6366f1}
.btn{padding:9px 18px;border-radius:6px;border:none;background:#6366f1;color:#fff;cursor:pointer;font-size:.875rem;transition:background .15s}
.btn:hover{background:#4f46e5}.btn:disabled{opacity:.45;cursor:default}
.main{flex:1;display:flex;overflow:hidden;min-height:0}
.sb{width:280px;min-width:220px;background:#111827;border-right:1px solid #1f2937;display:flex;flex-direction:column;overflow:hidden}
.sb-head{padding:10px 14px;font-size:.75rem;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #1f2937;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.back{cursor:pointer;color:#818cf8;font-size:.8rem;text-transform:none;font-weight:500}
.sb-body{flex:1;overflow-y:auto}
.acard{display:flex;gap:9px;padding:9px 14px;cursor:pointer;border-bottom:1px solid #1f2937;align-items:center;transition:background .12s}
.acard:hover{background:#1f2937}
.acard img{width:40px;height:54px;object-fit:cover;border-radius:3px;flex-shrink:0;background:#1f2937}
.acard-info{flex:1;min-width:0}
.acard-title{font-size:.82rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acard-slug{font-size:.7rem;color:#6b7280;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.epitem{padding:7px 14px;cursor:pointer;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:8px;transition:background .12s}
.epitem:hover{background:#1f2937}
.epitem.active{background:#1e1b4b;padding-left:12px;border-left:2px solid #6366f1}
.epnum{width:30px;text-align:center;font-size:.82rem;font-weight:600;color:#818cf8;flex-shrink:0}
.epinfo{flex:1;min-width:0}
.eptitle{font-size:.8rem}
.badges{display:flex;gap:3px;margin-top:3px}
.badge{font-size:.62rem;padding:1px 5px;border-radius:3px;background:#1f2937;color:#9ca3af}
.badge.sub{background:#1e3a5f;color:#60a5fa}
.badge.dub{background:#14291a;color:#4ade80}
.content{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.pvid{background:#000;flex-shrink:0}
video{width:100%;display:block;max-height:52vh}
.pinfo{padding:8px 14px;background:#111827;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:10px;flex-shrink:0;min-height:38px}
.now{font-size:.8rem;color:#9ca3af;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.skips{display:flex;gap:5px}
.sbtn{padding:4px 10px;border-radius:4px;border:1px solid #374151;background:transparent;color:#9ca3af;cursor:pointer;font-size:.75rem}
.sbtn:hover{background:#1f2937;color:#e2e8f0}
.dbg{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.dbg-head{padding:7px 14px;background:#111827;border-bottom:1px solid #1f2937;font-size:.77rem;font-weight:600;color:#6b7280;display:flex;align-items:center;gap:7px;flex-shrink:0}
.dot{width:7px;height:7px;border-radius:50%;background:#374151;flex-shrink:0}
.dot.on{background:#4ade80;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.dbg-body{flex:1;overflow-y:auto;font-family:monospace;font-size:.72rem;background:#07070e}
.drow{padding:5px 14px;border-bottom:1px solid #111827;line-height:1.5}
.drow.step{color:#a5b4fc}.drow.ok{color:#4ade80}.drow.err{color:#f87171}.drow.info{color:#6b7280}
.dsub{padding-top:2px;word-break:break-all}
.dsub.url{color:#60a5fa;font-size:.68rem}
.dsub.res{color:#bef264}
.dsub.err{color:#f87171}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#374151;gap:6px}
.empty-ico{font-size:2.5rem}
.empty-txt{font-size:.85rem}
.loading{text-align:center;padding:20px;color:#6b7280;font-size:.82rem}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#374151;border-radius:2px}
</style>
</head>
<body>
<div class="hdr">
  <div class="logo">&#9654; AniStream</div>
  <div class="sw">
    <input id="q" type="text" placeholder="Search anime&#8230;">
    <button class="btn" id="sbtn">Search</button>
  </div>
</div>
<div class="main">
  <div class="sb">
    <div class="sb-head">
      <span id="sblabel">Results</span>
      <span id="backbtn" class="back" style="display:none">&#8592; Back</span>
    </div>
    <div class="sb-body" id="sbbody"></div>
  </div>
  <div class="content">
    <div class="pvid" id="pvid" style="display:none"><video id="v" controls></video></div>
    <div class="pinfo" id="pinfo" style="display:none">
      <div class="now" id="nowplay"></div>
      <div class="skips" id="skips" style="display:none">
        <button class="sbtn" id="skip-intro">Skip Intro</button>
        <button class="sbtn" id="skip-outro">Skip Outro</button>
      </div>
    </div>
    <div class="dbg">
      <div class="dbg-head">
        <div class="dot" id="dot"></div>
        <span>API Pipeline Log</span>
      </div>
      <div class="dbg-body" id="dlog"></div>
    </div>
  </div>
</div>
<script>
(function () {
  'use strict';
  var hls = null, intro_ = null, outro_ = null;
  var searchResults_ = [], episodeStore_ = {};
  var currentAnime_ = null, activeEpEl_ = null;

  /* ── helpers ── */
  function $(id) { return document.getElementById(id); }
  function dot(on) { $('dot').className = 'dot' + (on ? ' on' : ''); }

  function log(cls, msg, sub, subCls) {
    var body = $('dlog');
    var row = document.createElement('div');
    row.className = 'drow ' + cls;
    row.textContent = msg;
    if (sub != null) {
      var s = document.createElement('div');
      s.className = 'dsub ' + (subCls || 'url');
      s.textContent = sub;
      row.appendChild(s);
    }
    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  function clearLog() { $('dlog').textContent = ''; }

  function renderSteps(steps) {
    (steps || []).forEach(function (s) {
      var hdr = 'Step ' + s.n + ': ' + s.label + (s.status ? ' → HTTP ' + s.status : '');
      log('step', hdr, s.url, 'url');
      if (s.result)  log('ok',   '  ↳ ' + s.result,  null, 'res');
      if (s.snippet) log('info', '  ↳ ' + s.snippet.substring(0, 120) + '…', null, 'res');
      if (s.error)   log('err',  '  ✗ ' + s.error,   null, 'err');
    });
  }

  function emptyState(icon, txt) {
    var wrap = document.createElement('div');
    wrap.className = 'empty';
    var ico = document.createElement('div');
    ico.className = 'empty-ico';
    ico.textContent = icon;
    var t = document.createElement('div');
    t.className = 'empty-txt';
    t.textContent = txt;
    wrap.appendChild(ico);
    wrap.appendChild(t);
    return wrap;
  }

  function loadingEl(txt) {
    var d = document.createElement('div');
    d.className = 'loading';
    d.textContent = txt || 'Loading…';
    return d;
  }

  /* ── search ── */
  function doSearch() {
    var q = $('q').value.trim();
    if (!q) return;
    clearLog(); dot(true);
    log('step', 'Searching: “' + q + '”');
    var body = $('sbbody');
    body.textContent = '';
    body.appendChild(loadingEl('Searching…'));
    $('sblabel').textContent = 'Results';
    $('backbtn').style.display = 'none';
    $('sbtn').disabled = true;

    fetch('/api/search?q=' + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        dot(false);
        $('sbtn').disabled = false;
        renderSteps(data.steps);
        searchResults_ = data.results || [];
        if (!data.ok || !searchResults_.length) {
          log('err', 'No results' + (data.error ? ': ' + data.error : ''));
          body.textContent = '';
          body.appendChild(emptyState('😕', 'No results found'));
          return;
        }
        log('ok', 'Found ' + searchResults_.length + ' result(s)');
        renderResults(searchResults_);
      })
      .catch(function (e) {
        dot(false);
        $('sbtn').disabled = false;
        log('err', 'Fetch error: ' + e);
      });
  }

  function renderResults(results) {
    var body = $('sbbody');
    body.textContent = '';
    results.forEach(function (r, idx) {
      var card = document.createElement('div');
      card.className = 'acard';
      card.dataset.idx = idx;

      var img = document.createElement('img');
      img.src = r.img;
      img.alt = '';
      img.loading = 'lazy';
      img.onerror = function () { this.style.visibility = 'hidden'; };

      var info = document.createElement('div');
      info.className = 'acard-info';

      var title = document.createElement('div');
      title.className = 'acard-title';
      title.textContent = r.title;

      var slug = document.createElement('div');
      slug.className = 'acard-slug';
      slug.textContent = r.slug;

      info.appendChild(title);
      info.appendChild(slug);
      card.appendChild(img);
      card.appendChild(info);

      card.addEventListener('click', function () {
        selectAnime(searchResults_[this.dataset.idx]);
      });
      body.appendChild(card);
    });
  }

  /* ── episode list ── */
  function backToSearch() {
    $('sblabel').textContent = 'Results';
    $('backbtn').style.display = 'none';
    renderResults(searchResults_);
  }

  function selectAnime(r) {
    currentAnime_ = r;
    clearLog(); dot(true);
    log('step', 'Loading episodes: ' + r.title + ' (' + r.slug + ')');
    var body = $('sbbody');
    body.textContent = '';
    body.appendChild(loadingEl('Loading episodes…'));
    var short = r.title.length > 24 ? r.title.substring(0, 23) + '…' : r.title;
    $('sblabel').textContent = short;
    $('backbtn').style.display = '';

    fetch('/api/episodes?slug=' + encodeURIComponent(r.slug))
      .then(function (x) { return x.json(); })
      .then(function (data) {
        dot(false);
        renderSteps(data.steps);
        if (!data.ok) {
          log('err', 'Failed: ' + (data.error || 'unknown'));
          body.textContent = '';
          body.appendChild(emptyState('⚠️', 'Could not load episodes'));
          return;
        }
        log('ok', data.episodes.length + ' episode(s)  |  anime_id=' + data.anime_id);
        episodeStore_ = {};
        data.episodes.forEach(function (ep) { episodeStore_[ep.id] = ep; });
        renderEpisodes(data.episodes);
      })
      .catch(function (e) { dot(false); log('err', 'Fetch error: ' + e); });
  }

  function renderEpisodes(episodes) {
    var body = $('sbbody');
    body.textContent = '';
    episodes.forEach(function (ep) {
      var row = document.createElement('div');
      row.className = 'epitem';
      row.id = 'ep-' + ep.id;
      row.dataset.epid = ep.id;

      var num = document.createElement('div');
      num.className = 'epnum';
      num.textContent = ep.num;

      var info = document.createElement('div');
      info.className = 'epinfo';

      var title = document.createElement('div');
      title.className = 'eptitle';
      title.textContent = 'Episode ' + ep.num;

      var badges = document.createElement('div');
      badges.className = 'badges';

      if (ep.has_sub) {
        var bs = document.createElement('span');
        bs.className = 'badge sub';
        bs.textContent = 'SUB';
        badges.appendChild(bs);
      }
      if (ep.has_dub) {
        var bd = document.createElement('span');
        bd.className = 'badge dub';
        bd.textContent = 'DUB';
        badges.appendChild(bd);
      }
      var bid = document.createElement('span');
      bid.className = 'badge';
      bid.textContent = 'id:' + ep.id;
      badges.appendChild(bid);

      info.appendChild(title);
      info.appendChild(badges);
      row.appendChild(num);
      row.appendChild(info);

      row.addEventListener('click', function () {
        playEp(episodeStore_[this.dataset.epid], this);
      });
      body.appendChild(row);
    });
  }

  /* ── stream ── */
  function playEp(ep, el) {
    if (activeEpEl_) activeEpEl_.classList.remove('active');
    el.classList.add('active');
    activeEpEl_ = el;

    clearLog(); dot(true);
    log('step', 'Loading stream — Episode ' + ep.num);
    log('info', 'data_ids = ' + ep.data_ids.substring(0, 50) + '…');

    if (hls) { hls.destroy(); hls = null; }
    $('pvid').style.display = 'none';
    $('pinfo').style.display = 'none';

    fetch('/api/stream?data_ids=' + encodeURIComponent(ep.data_ids))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        dot(false);
        renderSteps(data.steps);
        if (!data.ok) {
          log('err', '✗ Stream error: ' + (data.error || 'unknown'));
          return;
        }

        intro_ = data.intro || null;
        outro_ = data.outro || null;

        log('ok', '✓ m3u8 ready', data.m3u8_raw, 'res');
        if (intro_) log('info', '  Intro: ' + intro_.start + 's – ' + intro_.end + 's');
        if (outro_) log('info', '  Outro: ' + outro_.start + 's – ' + outro_.end + 's');
        if (data.tracks && data.tracks.length) {
          log('info', '  Subtitles: ' + data.tracks.map(function (t) { return t.label; }).join(', '));
        }

        $('pvid').style.display = 'block';
        $('pinfo').style.display = 'flex';
        $('nowplay').textContent = (currentAnime_ ? currentAnime_.title + ' — ' : '') + 'Episode ' + ep.num;
        $('skips').style.display = (intro_ || outro_) ? '' : 'none';

        var v = $('v');
        if (!Hls.isSupported()) { log('err', 'HLS.js not supported'); return; }
        hls = new Hls({ enableWorker: false });
        hls.loadSource(window.location.origin + data.m3u8);
        hls.attachMedia(v);
        hls.on(Hls.Events.MANIFEST_PARSED, function (e, d) {
          log('ok', '✓ HLS manifest — ' + d.levels.length + ' quality level(s)');
          v.play().catch(function () {});
        });
        hls.on(Hls.Events.ERROR, function (e, d) {
          if (d.fatal) log('err', '✗ HLS: ' + d.details + (d.response ? ' (HTTP ' + d.response.code + ')' : ''));
        });
      })
      .catch(function (e) { dot(false); log('err', 'Fetch error: ' + e); });
  }

  /* ── skip buttons ── */
  $('skip-intro').addEventListener('click', function () {
    if (intro_) $('v').currentTime = intro_.end;
  });
  $('skip-outro').addEventListener('click', function () {
    if (outro_) $('v').currentTime = outro_.end;
  });

  /* ── wire up search ── */
  $('sbtn').addEventListener('click', doSearch);
  $('q').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
  $('backbtn').addEventListener('click', backToSearch);

  /* ── initial state ── */
  $('sbbody').appendChild(emptyState('🔍', 'Search for an anime above'));
  log('info', 'Ready. Use the search bar to begin.');
}());
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_cors()
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        if path in ("/", "/player"):
            body = PLAYER_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",   "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/search":
            self.send_json(api_search(params.get("q", "")))
            return

        if path == "/api/episodes":
            self.send_json(api_episodes(params.get("slug", "")))
            return

        if path == "/api/stream":
            self.send_json(api_stream(params.get("data_ids", ""), params.get("type", "sub")))
            return

        if path.startswith("/ext/"):
            rest  = path[5:]
            slash = rest.find("/")
            host  = rest[:slash] if slash != -1 else rest
            fpath = rest[slash:] if slash != -1 else "/"
            self._proxy(host, fpath)
            return

        self._proxy("cdn.mewstream.buzz", path)

    def _proxy(self, host, path):
        try:
            r       = upstream_get(host, path)
            ct      = r.headers.get("content-type", "")
            is_m3u8 = ".m3u8" in path or "mpegurl" in ct

            self.send_response(r.status_code)
            self.send_cors()

            if is_m3u8:
                body = rewrite_m3u8(r.text).encode("utf-8")
                print(f"[m3u8] {host}{path[-40:]}  len={len(body)}", flush=True)
                self.send_header("Content-Type",   "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = r.content
                print(f"[seg] {r.status_code} {host[:4]} …{path[-22:]}")
                self.send_header("Content-Type",   ct or "video/MP2T")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        except Exception as e:
            print(f"[ERR] {host}{path[:40]} — {e}")
            try:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(str(e).encode())
            except Exception:
                pass


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = Server(("127.0.0.1", PORT), Handler)
    print(f"\n[+] Open Chrome Incognito:  http://localhost:{PORT}\n")
    server.serve_forever()
