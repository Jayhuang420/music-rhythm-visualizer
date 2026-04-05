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
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from generator import (
    generate_spectrum,
    hex_to_rgba,
    render_frame,
    encode_to_prores,
)

app = FastAPI(title="音樂符號律動動畫產生器")

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
# 前端頁面
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
      <select id="type">
        <option value="bar">直條頻譜 (Bar)</option>
        <option value="circular">圓環頻譜 (Circular)</option>
        <option value="wave">波形線 (Wave)</option>
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
async def index():
    return HTML_PAGE


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
