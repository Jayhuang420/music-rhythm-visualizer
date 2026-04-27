"""
音樂符號律動動畫產生器 — Web 應用
FastAPI + 內嵌前端 UI
"""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request, Cookie
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from generator import (
    generate_spectrum,
    hex_to_rgba,
    render_frame,
    encode_to_prores,
)

app = FastAPI(title="音樂符號律動動畫產生器")

# 預覽 GIF 靜態目錄
PREVIEW_DIR = Path(__file__).parent / "previews"
if PREVIEW_DIR.exists():
    app.mount("/previews", StaticFiles(directory=str(PREVIEW_DIR)), name="previews")

# 各動畫類型的「適合曲風」+「建議參數」
# bpm: 建議節奏範圍 / bars: 建議頻譜條數 / duration: 建議時長（秒）
GENRE_INFO = {
    "dots":           {"label": "底部點陣律動",   "genre": "Lo-fi、Chill、Study Music、深夜放鬆 BGM",
                       "bpm": "70–90",   "bars": "32–48",  "duration": "30–60s"},
    "bar":            {"label": "直條頻譜",       "genre": "Pop、K-pop、流行樂、EDM 通用萬用款",
                       "bpm": "100–128", "bars": "64–80",  "duration": "30–60s"},
    "circular":       {"label": "圓環頻譜",       "genre": "電子、Techno、舞曲、Future Bass",
                       "bpm": "128–140", "bars": "64",     "duration": "30–60s"},
    "wave":           {"label": "波形線",         "genre": "Ambient、療癒系、冥想、瑜伽音樂",
                       "bpm": "60–80",   "bars": "64–96",  "duration": "60–120s"},
    "pulse_ring":     {"label": "脈衝光環",       "genre": "Lo-fi、Deep House、放鬆、夜晚 Vibe",
                       "bpm": "80–100",  "bars": "32",     "duration": "30–60s"},
    "bouncing_balls": {"label": "彈跳小球",       "genre": "兒歌、輕快流行、Indie Pop、Disco",
                       "bpm": "110–130", "bars": "24",     "duration": "15–30s"},
    "particle_burst": {"label": "粒子爆發",       "genre": "EDM、Trap、Bass Drop、Festival 高潮段",
                       "bpm": "128–150", "bars": "64",     "duration": "10–20s"},
    "vinyl":          {"label": "黑膠唱片",       "genre": "Jazz、City Pop、復古 R&B、Soul、爵士",
                       "bpm": "80–100",  "bars": "64",     "duration": "30–60s"},
    "mountain":       {"label": "山形頻譜",       "genre": "自然系、Acoustic、Folk、空靈 Indie",
                       "bpm": "70–90",   "bars": "64–96",  "duration": "30–60s"},
    "ripple":         {"label": "水波紋",         "genre": "治癒系、Sleep Music、夜曲、ASMR",
                       "bpm": "50–70",   "bars": "24",     "duration": "60–120s"},
    "starburst":      {"label": "星芒散射",       "genre": "Hip-hop、Trap、動感、街舞 Beat",
                       "bpm": "85–95",   "bars": "48",     "duration": "15–30s"},
    "retro_grid":     {"label": "80s 復古網格",   "genre": "Synthwave、Vaporwave、Retrowave、80s 懷舊",
                       "bpm": "95–115",  "bars": "32",     "duration": "30–60s"},
    "trail":          {"label": "拖尾彗星",       "genre": "House、Tech House、Progressive、舞池 Mix",
                       "bpm": "120–128", "bars": "32",     "duration": "30–60s"},
    "scrolling_line": {"label": "滾動心電圖",     "genre": "Beat 教學、Metronome、節拍器、極簡電音",
                       "bpm": "60–140",  "bars": "32",     "duration": "10–20s"},
    "grid_matrix":    {"label": "LED 方塊矩陣",   "genre": "Chiptune、Game Music、復古電子、8-bit",
                       "bpm": "120–160", "bars": "16",     "duration": "15–30s"},
}

# 密碼設定
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "oldjvip")
# 已驗證的 token 集合（記憶體內，重啟會清空）
verified_tokens: set[str] = set()

# 輸出目錄
OUTPUT_DIR = Path(tempfile.gettempdir()) / "music_viz_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# 任務追蹤
tasks: dict[str, dict] = {}

# 定期清理超過 30 分鐘的檔案
MAX_AGE_SECONDS = 1800


def cleanup_old_files():
    now = time.time()
    for f in OUTPUT_DIR.iterdir():
        if f.is_file() and now - f.stat().st_mtime > MAX_AGE_SECONDS:
            f.unlink(missing_ok=True)
    expired = [tid for tid, t in tasks.items() if now - t.get("created", now) > MAX_AGE_SECONDS]
    for tid in expired:
        tasks.pop(tid, None)


# ---------------------------------------------------------------------------
# 密碼驗證頁面
# ---------------------------------------------------------------------------

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Music Rhythm Visualizer - 驗證</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    background:#0a0a1a;color:#e0e0e0;
    min-height:100vh;display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    padding:2rem 1rem;
  }
  .lock-icon{font-size:3rem;margin-bottom:1rem;opacity:.6}
  h1{
    font-size:1.6rem;margin-bottom:.3rem;
    background:linear-gradient(135deg,#00ffaa,#7b68ee);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  }
  .subtitle{color:#666;font-size:.85rem;margin-bottom:2rem}
  .login-card{
    background:#12122a;border:1px solid #2a2a4a;border-radius:16px;
    padding:2.5rem 2rem;width:100%;max-width:380px;text-align:center;
  }
  .input-group{margin-bottom:1.2rem}
  .input-group label{
    display:block;font-size:.8rem;color:#aaa;margin-bottom:.4rem;
    text-align:left;font-weight:500;
  }
  .input-group input{
    width:100%;background:#1a1a35;border:1px solid #333;border-radius:10px;
    color:#fff;padding:.7rem 1rem;font-size:1rem;outline:none;
    text-align:center;letter-spacing:2px;
    transition:border-color .2s;
  }
  .input-group input:focus{border-color:#00ffaa}
  .btn{
    width:100%;padding:.75rem;border:none;border-radius:10px;
    font-size:1rem;font-weight:600;cursor:pointer;
    background:linear-gradient(135deg,#00ffaa,#00cc88);color:#0a0a1a;
    transition:opacity .2s,transform .1s;
    margin-top:.5rem;
  }
  .btn:hover{opacity:.9}
  .btn:active{transform:scale(.98)}
  .error-msg{
    color:#ff6b6b;font-size:.85rem;margin-top:.8rem;
    min-height:1.2em;
  }
  .shake{animation:shake .4s ease-in-out}
  @keyframes shake{
    0%,100%{transform:translateX(0)}
    20%,60%{transform:translateX(-8px)}
    40%,80%{transform:translateX(8px)}
  }
</style>
</head>
<body>
<div class="lock-icon">&#128274;</div>
<h1>Music Rhythm Visualizer</h1>
<p class="subtitle">請輸入密碼以進入</p>

<div class="login-card">
  <form id="loginForm" onsubmit="return handleLogin(event)">
    <div class="input-group">
      <label>密碼</label>
      <input type="password" id="password" placeholder="Enter password" autofocus>
    </div>
    <button class="btn" type="submit">進入</button>
  </form>
  <div class="error-msg" id="errorMsg"></div>
</div>

<script>
async function handleLogin(e) {
  e.preventDefault();
  const pw = document.getElementById('password').value;
  const errEl = document.getElementById('errorMsg');
  const card = document.querySelector('.login-card');
  errEl.textContent = '';

  const res = await fetch('/api/verify', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: pw}),
  });
  const data = await res.json();
  if (data.ok) {
    window.location.href = '/app';
  } else {
    errEl.textContent = '密碼錯誤，請重試';
    card.classList.remove('shake');
    void card.offsetWidth;
    card.classList.add('shake');
    document.getElementById('password').value = '';
    document.getElementById('password').focus();
  }
  return false;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 前端主頁面
# ---------------------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>音樂符號律動動畫產生器</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    background:#0a0a1a;color:#e0e0e0;
    min-height:100vh;display:flex;flex-direction:column;align-items:center;
    padding:2rem 1rem;
  }
  h1{
    font-size:1.8rem;margin-bottom:.3rem;
    background:linear-gradient(135deg,#00ffaa,#7b68ee);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  }
  .subtitle{color:#888;font-size:.9rem;margin-bottom:2rem}
  .card{
    background:#12122a;border:1px solid #2a2a4a;border-radius:16px;
    padding:2rem;width:100%;max-width:560px;
  }
  .row{display:flex;gap:1rem;margin-bottom:1rem}
  .field{flex:1;display:flex;flex-direction:column}
  label{font-size:.8rem;color:#aaa;margin-bottom:.3rem;font-weight:500}
  select,input[type=number],input[type=text]{
    background:#1a1a35;border:1px solid #333;border-radius:8px;
    color:#fff;padding:.5rem .7rem;font-size:.9rem;outline:none;
    transition:border-color .2s;
  }
  select:focus,input:focus{border-color:#00ffaa}
  input[type=color]{
    width:100%;height:38px;border:1px solid #333;border-radius:8px;
    background:#1a1a35;cursor:pointer;padding:2px;
  }
  .checkbox-row{
    display:flex;align-items:center;gap:.5rem;margin-bottom:1.2rem;
  }
  .checkbox-row input{accent-color:#00ffaa}
  .btn{
    width:100%;padding:.8rem;border:none;border-radius:10px;
    font-size:1rem;font-weight:600;cursor:pointer;
    background:linear-gradient(135deg,#00ffaa,#00cc88);color:#0a0a1a;
    transition:opacity .2s,transform .1s;
  }
  .btn:hover{opacity:.9}
  .btn:active{transform:scale(.98)}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .progress{
    margin-top:1rem;display:none;
  }
  .progress-bar{
    height:6px;background:#1a1a35;border-radius:3px;overflow:hidden;
    margin-bottom:.5rem;
  }
  .progress-fill{
    height:100%;background:linear-gradient(90deg,#00ffaa,#7b68ee);
    width:0%;transition:width .3s;border-radius:3px;
  }
  .progress-text{font-size:.8rem;color:#888;text-align:center}
  .download{
    display:none;margin-top:1rem;text-align:center;
  }
  .download a{
    display:inline-block;padding:.7rem 2rem;
    background:linear-gradient(135deg,#7b68ee,#6c5ce7);
    color:#fff;border-radius:10px;text-decoration:none;
    font-weight:600;transition:opacity .2s;
  }
  .download a:hover{opacity:.85}
  .preview-section{
    margin-top:1.5rem;display:none;text-align:center;
  }
  .preview-section img{
    max-width:100%;border-radius:8px;border:1px solid #2a2a4a;
  }
  .preview-label{font-size:.75rem;color:#666;margin-top:.3rem}

  /* 動畫類型預覽（下拉選單下方） */
  .type-preview{
    margin-top:.6rem;background:#0a0a20;border:1px solid #2a2a4a;
    border-radius:10px;padding:.7rem;display:flex;gap:.9rem;
    align-items:flex-start;
  }
  .type-preview img{
    width:160px;height:88px;object-fit:cover;border-radius:6px;
    background:#000;flex-shrink:0;
  }
  .type-preview .meta{flex:1;min-width:0}
  .type-preview .meta .title{
    font-size:.9rem;color:#fff;font-weight:600;margin-bottom:.3rem;
  }
  .type-preview .meta .genre{
    font-size:.72rem;color:#9aa;line-height:1.5;margin-bottom:.4rem;
  }
  .type-preview .meta .genre b{
    color:#00ffaa;font-weight:500;
  }
  .type-preview .params{
    display:flex;gap:.4rem;flex-wrap:wrap;
  }
  .type-preview .params .chip{
    background:#1a1a35;border:1px solid #2a2a4a;border-radius:6px;
    padding:.18rem .5rem;font-size:.68rem;color:#bbf;line-height:1.3;
    display:inline-flex;align-items:center;gap:.2rem;
  }
  .type-preview .params .chip span{color:#fff;font-weight:600;}
  .type-preview .params .chip .lab{color:#7b8;font-size:.62rem;}
  .apply-btn{
    margin-top:.45rem;font-size:.68rem;color:#0a0a1a;
    background:linear-gradient(135deg,#00ffaa,#7b68ee);
    border:none;border-radius:6px;padding:.28rem .7rem;cursor:pointer;
    font-weight:600;transition:opacity .2s;
  }
  .apply-btn:hover{opacity:.85}
  .error{
    margin-top:1rem;color:#ff6b6b;font-size:.85rem;display:none;text-align:center;
  }
  footer{margin-top:2rem;color:#444;font-size:.75rem}
</style>
</head>
<body>
<h1>Music Rhythm Visualizer</h1>
<p class="subtitle">產生去背頻譜律動動畫素材 (MOV ProRes 4444)</p>

<div class="card">
  <div class="row">
    <div class="field">
      <label>動畫類型</label>
      <select id="type" onchange="updateTypePreview()">
        <optgroup label="── 經典 ──">
          <option value="dots">底部點陣律動 (Dots) ★</option>
          <option value="bar">直條頻譜 (Bar)</option>
          <option value="circular">圓環頻譜 (Circular)</option>
          <option value="wave">波形線 (Wave)</option>
        </optgroup>
        <optgroup label="── YT 流行款 ──">
          <option value="pulse_ring">脈衝光環 (Pulse Ring)</option>
          <option value="bouncing_balls">彈跳小球 (Bouncing Balls)</option>
          <option value="particle_burst">粒子爆發 (Particle Burst)</option>
          <option value="vinyl">黑膠唱片 (Vinyl)</option>
          <option value="mountain">山形頻譜 (Mountain)</option>
          <option value="ripple">水波紋 (Ripple)</option>
          <option value="starburst">星芒散射 (Starburst)</option>
          <option value="retro_grid">80s 復古網格 (Retro Grid)</option>
          <option value="trail">拖尾彗星 (Trail)</option>
          <option value="scrolling_line">滾動心電圖 (EKG Line)</option>
          <option value="grid_matrix">LED 方塊矩陣 (Grid Matrix)</option>
        </optgroup>
      </select>
    </div>
    <div class="field">
      <label>尺寸風格</label>
      <select id="style">
        <option value="compact">小型集中 (Lo-fi)</option>
        <option value="full">佔滿寬度</option>
      </select>
    </div>
  </div>

  <div class="type-preview" id="typePreview">
    <img id="typePreviewImg" src="/previews/dots.gif" alt="preview">
    <div class="meta">
      <div class="title" id="typePreviewTitle">底部點陣律動</div>
      <div class="genre"><b>適合曲風：</b><span id="typePreviewGenre">Lo-fi、Chill、Study Music、深夜放鬆 BGM</span></div>
      <div class="params">
        <span class="chip"><span class="lab">BPM</span><span id="typePreviewBpm">70–90</span></span>
        <span class="chip"><span class="lab">頻譜條數</span><span id="typePreviewBars">32–48</span></span>
        <span class="chip"><span class="lab">建議時長</span><span id="typePreviewDur">30–60s</span></span>
      </div>
      <button class="apply-btn" type="button" onclick="applySuggestedParams()">一鍵套用建議</button>
    </div>
  </div>

  <div class="row">
    <div class="field">
      <label>時長 (秒)</label>
      <input type="number" id="duration" value="10" min="1" max="60" step="1">
    </div>
    <div class="field">
      <label>BPM</label>
      <input type="number" id="bpm" value="120" min="40" max="240" step="1">
    </div>
    <div class="field">
      <label>FPS</label>
      <input type="number" id="fps" value="30" min="24" max="60" step="1">
    </div>
  </div>

  <div class="row">
    <div class="field">
      <label>解析度 (寬)</label>
      <input type="number" id="width" value="1920" min="320" max="3840" step="1">
    </div>
    <div class="field">
      <label>解析度 (高)</label>
      <input type="number" id="height" value="1080" min="240" max="2160" step="1">
    </div>
    <div class="field">
      <label>頻譜條數</label>
      <input type="number" id="bars" value="64" min="8" max="256" step="1">
    </div>
  </div>

  <div class="row">
    <div class="field">
      <label>主色調</label>
      <input type="color" id="color" value="#ffffff">
    </div>
  </div>

  <div class="checkbox-row">
    <input type="checkbox" id="glow" checked>
    <label for="glow" style="margin-bottom:0">發光效果</label>
  </div>

  <button class="btn" id="generateBtn" onclick="startGenerate()">產生動畫</button>

  <div class="progress" id="progress">
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
    <div class="progress-text" id="progressText">準備中...</div>
  </div>

  <div class="error" id="error"></div>

  <div class="download" id="download">
    <a id="downloadLink" href="#" download>下載 MOV 檔案</a>
  </div>

  <div class="preview-section" id="previewSection">
    <img id="previewImg" src="" alt="preview">
    <div class="preview-label">預覽 (深色背景模擬)</div>
  </div>
</div>

<footer>輸出格式：MOV ProRes 4444 (含 Alpha 透明通道) — 可直接匯入剪輯軟體</footer>

<script>
let pollTimer = null;
let GENRE_INFO = {};

// 載入曲風資訊
fetch('/api/genres').then(r => r.json()).then(data => {
  GENRE_INFO = data;
  updateTypePreview();
});

function updateTypePreview() {
  const t = document.getElementById('type').value;
  const info = GENRE_INFO[t];
  if (!info) return;
  // 直接設新 URL（含 cache-buster），瀏覽器會視為新資源並從第一幀重新播放動畫
  document.getElementById('typePreviewImg').src = `/previews/${t}.gif?t=${Date.now()}`;
  document.getElementById('typePreviewTitle').textContent = info.label;
  document.getElementById('typePreviewGenre').textContent = info.genre;
  document.getElementById('typePreviewBpm').textContent = info.bpm || '–';
  document.getElementById('typePreviewBars').textContent = info.bars || '–';
  document.getElementById('typePreviewDur').textContent = info.duration || '–';
}

// 將「範圍」字串（例如 "70–90" 或 "30–60s"）取中位數整數
function parseRangeMid(str) {
  if (!str) return null;
  const nums = str.match(/\d+/g);
  if (!nums || !nums.length) return null;
  if (nums.length === 1) return parseInt(nums[0], 10);
  return Math.round((parseInt(nums[0], 10) + parseInt(nums[1], 10)) / 2);
}

function applySuggestedParams() {
  const t = document.getElementById('type').value;
  const info = GENRE_INFO[t];
  if (!info) return;
  const bpm = parseRangeMid(info.bpm);
  const bars = parseRangeMid(info.bars);
  const dur = parseRangeMid(info.duration);
  if (bpm)  document.getElementById('bpm').value = bpm;
  if (bars) document.getElementById('bars').value = bars;
  if (dur)  document.getElementById('duration').value = Math.min(dur, 60); // 後端最多 60s
  // 視覺回饋
  const btn = event.target;
  const orig = btn.textContent;
  btn.textContent = '✓ 已套用';
  setTimeout(() => { btn.textContent = orig; }, 1200);
}

async function startGenerate() {
  const btn = document.getElementById('generateBtn');
  const progress = document.getElementById('progress');
  const download = document.getElementById('download');
  const error = document.getElementById('error');
  const preview = document.getElementById('previewSection');

  btn.disabled = true;
  progress.style.display = 'block';
  download.style.display = 'none';
  error.style.display = 'none';
  preview.style.display = 'none';
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressText').textContent = '準備中...';

  const params = {
    type: document.getElementById('type').value,
    style: document.getElementById('style').value,
    duration: parseFloat(document.getElementById('duration').value),
    bpm: parseFloat(document.getElementById('bpm').value),
    fps: parseInt(document.getElementById('fps').value),
    width: parseInt(document.getElementById('width').value),
    height: parseInt(document.getElementById('height').value),
    bars: parseInt(document.getElementById('bars').value),
    color: document.getElementById('color').value,
    glow: document.getElementById('glow').checked,
  };

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(params),
    });
    const data = await res.json();
    if (!data.task_id) throw new Error(data.detail || '啟動失敗');
    pollProgress(data.task_id);
  } catch(e) {
    error.textContent = e.message;
    error.style.display = 'block';
    btn.disabled = false;
    progress.style.display = 'none';
  }
}

function pollProgress(taskId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${taskId}`);
      const data = await res.json();
      const fill = document.getElementById('progressFill');
      const text = document.getElementById('progressText');

      if (data.status === 'rendering') {
        fill.style.width = data.progress + '%';
        text.textContent = `渲染中... ${data.progress}%`;
      } else if (data.status === 'encoding') {
        fill.style.width = '95%';
        text.textContent = '編碼 ProRes 4444...';
      } else if (data.status === 'done') {
        clearInterval(pollTimer);
        fill.style.width = '100%';
        text.textContent = '完成！';
        document.getElementById('downloadLink').href = `/api/download/${taskId}`;
        document.getElementById('download').style.display = 'block';
        document.getElementById('generateBtn').disabled = false;
        // 顯示預覽
        document.getElementById('previewImg').src = `/api/preview/${taskId}?t=${Date.now()}`;
        document.getElementById('previewSection').style.display = 'block';
      } else if (data.status === 'error') {
        clearInterval(pollTimer);
        document.getElementById('error').textContent = data.message || '產生失敗';
        document.getElementById('error').style.display = 'block';
        document.getElementById('generateBtn').disabled = false;
        document.getElementById('progress').style.display = 'none';
      }
    } catch(e) {
      // ignore transient errors
    }
  }, 800);
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index(auth: str = Cookie(default=None)):
    if auth and auth in verified_tokens:
        return RedirectResponse("/app", status_code=302)
    return LOGIN_PAGE


@app.get("/app", response_class=HTMLResponse)
async def main_app(auth: str = Cookie(default=None)):
    if not auth or auth not in verified_tokens:
        return RedirectResponse("/", status_code=302)
    return HTML_PAGE


@app.get("/api/genres")
async def api_genres():
    """回傳所有動畫類型的曲風資訊。"""
    return GENRE_INFO


@app.post("/api/verify")
async def api_verify(request: Request):
    body = await request.json()
    if body.get("password") == ACCESS_PASSWORD:
        token = uuid.uuid4().hex
        verified_tokens.add(token)
        resp = JSONResponse({"ok": True})
        resp.set_cookie("auth", token, httponly=True, samesite="lax", max_age=86400)
        return resp
    return JSONResponse({"ok": False}, status_code=401)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def api_generate(request: Request):
    cleanup_old_files()
    body = await request.json()

    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "created": time.time(),
        "params": body,
    }

    asyncio.get_event_loop().run_in_executor(None, _render_task, task_id, body)
    return {"task_id": task_id}


@app.get("/api/status/{task_id}")
async def api_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        return JSONResponse({"status": "error", "message": "任務不存在"}, 404)
    return {
        "status": task["status"],
        "progress": task.get("progress", 0),
        "message": task.get("message", ""),
    }


@app.get("/api/download/{task_id}")
async def api_download(task_id: str):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return JSONResponse({"detail": "檔案不存在"}, 404)
    path = task["output_path"]
    if not os.path.exists(path):
        return JSONResponse({"detail": "檔案已過期"}, 404)
    filename = f"music_viz_{task['params'].get('type','bar')}.mov"
    return FileResponse(path, filename=filename, media_type="video/quicktime")


@app.get("/api/preview/{task_id}")
async def api_preview(task_id: str):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return JSONResponse({"detail": "預覽不存在"}, 404)
    preview_path = task.get("preview_path")
    if not preview_path or not os.path.exists(preview_path):
        return JSONResponse({"detail": "預覽不存在"}, 404)
    return FileResponse(preview_path, media_type="image/png")


# ---------------------------------------------------------------------------
# 背景渲染任務
# ---------------------------------------------------------------------------

def _render_task(task_id: str, params: dict):
    try:
        anim_type = params.get("type", "bar")
        bar_style = params.get("style", "compact")
        duration = min(float(params.get("duration", 10)), 60)
        bpm = float(params.get("bpm", 120))
        fps = int(params.get("fps", 30))
        width = int(params.get("width", 1920))
        height = int(params.get("height", 1080))
        num_bars = int(params.get("bars", 64))
        color_hex = params.get("color", "#FFFFFF")
        glow = params.get("glow", True)

        color = hex_to_rgba(color_hex)
        seeds = np.random.uniform(0, 100, num_bars)
        total_frames = int(duration * fps)

        tasks[task_id]["status"] = "rendering"

        # 暫存目錄
        tmp_dir = tempfile.mkdtemp(prefix="music_viz_web_")
        frames_dir = os.path.join(tmp_dir, "frames")
        os.makedirs(frames_dir)

        prev = None
        for i in range(total_frames):
            img, prev = render_frame(
                i, fps, anim_type, width, height, color,
                num_bars, bpm, glow, seeds, prev, bar_style
            )
            img.save(os.path.join(frames_dir, f"{i:06d}.png"), "PNG")

            if (i + 1) % max(1, fps // 2) == 0 or i == total_frames - 1:
                tasks[task_id]["progress"] = int((i + 1) / total_frames * 100)

        # 產生預覽圖（取中間幀疊在深色底上）
        preview_path = str(OUTPUT_DIR / f"{task_id}_preview.png")
        mid_frame = os.path.join(frames_dir, f"{total_frames // 2:06d}.png")
        _make_preview(mid_frame, preview_path)

        # 編碼
        tasks[task_id]["status"] = "encoding"
        output_path = str(OUTPUT_DIR / f"{task_id}.mov")
        encode_to_prores(frames_dir, output_path, fps, width, height)

        # 清理幀
        shutil.rmtree(tmp_dir, ignore_errors=True)

        tasks[task_id]["status"] = "done"
        tasks[task_id]["output_path"] = output_path
        tasks[task_id]["preview_path"] = preview_path

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["message"] = str(e)


def _make_preview(frame_path: str, output_path: str):
    """將透明幀疊在深色背景上產生預覽圖。"""
    from PIL import Image
    bg = Image.new("RGBA", (960, 540), (18, 18, 40, 255))
    fg = Image.open(frame_path).convert("RGBA")
    fg = fg.resize((960, 540), Image.LANCZOS)
    bg = Image.alpha_composite(bg, fg)
    bg.save(output_path, "PNG")
