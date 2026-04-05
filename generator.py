#!/usr/bin/env python3
"""
音樂符號律動動畫產生器
======================
隨機產生頻譜波形律動動畫，輸出為去背 MOV (ProRes 4444) 透明影片素材。
參考風格：lo-fi 音樂頻道常見的纖細鏡像直條頻譜。

支援三種動畫類型：
  - bar      : 鏡像直條頻譜（lo-fi 風格，纖細白色條紋上下對稱）
  - circular : 圓環頻譜
  - wave     : 波形線

使用方式：
  python generator.py --type bar --duration 10 --bpm 128
  python generator.py --type bar --style compact --color "#FFFFFF"
"""

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ---------------------------------------------------------------------------
# 數學工具
# ---------------------------------------------------------------------------

def noise(t, seed=0.0):
    """多層正弦疊加模擬平滑噪聲。"""
    return (
        math.sin(t * 1.0 + seed) * 0.5
        + math.sin(t * 2.3 + seed * 1.7) * 0.3
        + math.sin(t * 4.1 + seed * 3.1) * 0.15
        + math.sin(t * 7.9 + seed * 5.3) * 0.05
    )


def beat_pulse(t, bpm):
    """BPM 拍點脈衝，在拍點瞬間為 1 並指數衰減。"""
    phase = (t * bpm / 60.0) % 1.0
    return max(0.0, 1.0 - phase * 3.0) ** 2


def sub_beat_pulse(t, bpm, subdivision=2):
    """子拍脈衝。"""
    phase = (t * bpm / 60.0 * subdivision) % 1.0
    return max(0.0, 1.0 - phase * 4.0) ** 2


def hex_to_rgba(hex_color, alpha=255):
    """hex 色碼 → RGBA tuple。"""
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def smoothstep(edge0, edge1, x):
    """平滑階梯函數。"""
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# 頻譜數據生成
# ---------------------------------------------------------------------------

def generate_spectrum(num_bars, t, bpm, seeds, prev_spectrum=None, smoothing=0.3):
    """
    產生一幀頻譜數據 (0~1)。
    使用多層 noise + BPM 脈衝，並以 smoothing 平滑跨幀過渡。
    """
    values = np.zeros(num_bars)
    pulse = beat_pulse(t, bpm)
    sub_pulse = sub_beat_pulse(t, bpm)

    for i in range(num_bars):
        s = seeds[i]
        # 頻率權重：低頻高、高頻低（模擬真實頻譜包絡）
        freq_w = 1.0 - (i / num_bars) * 0.5
        # 中頻微微突起
        mid_bump = math.exp(-((i / num_bars - 0.35) ** 2) / 0.05) * 0.2
        # 多層 noise
        n = noise(t * 2.5, s) * 0.5 + 0.5
        # 拍點驅動
        beat_w = 1.0 - (i / num_bars) * 0.6
        beat = pulse * beat_w * 0.5 + sub_pulse * 0.15
        # 隨機閃爍
        flicker = noise(t * 6.0, s + 50) * 0.1
        # 組合
        val = (n * freq_w + mid_bump) * 0.45 + beat + flicker
        values[i] = max(0.02, min(1.0, val))

    # 跨幀平滑
    if prev_spectrum is not None:
        values = prev_spectrum * smoothing + values * (1.0 - smoothing)

    return values


# ---------------------------------------------------------------------------
# 繪製：鏡像直條頻譜（lo-fi 風格）
# ---------------------------------------------------------------------------

def draw_bar_spectrum(draw, width, height, spectrum, color, glow_layer, style):
    """
    繪製上下鏡像的直條頻譜。
    style='compact' → 小型集中在中央（參考影片風格）
    style='full'    → 佔滿畫面寬度
    """
    num_bars = len(spectrum)

    if style == 'compact':
        # 小型頻譜，佔畫面寬度 40%，高度 15%
        viz_width = width * 0.40
        max_bar_h = height * 0.08
    else:
        viz_width = width * 0.80
        max_bar_h = height * 0.30

    bar_gap = viz_width / num_bars
    bar_w = max(1, bar_gap * 0.65)
    start_x = (width - viz_width) / 2
    center_y = height / 2

    r, g, b = color[0], color[1], color[2]

    for i, val in enumerate(spectrum):
        bar_h = val * max_bar_h
        if bar_h < 1:
            continue

        x = start_x + i * bar_gap
        # 透明度隨高度變化
        alpha = int(120 + val * 135)
        alpha = min(255, alpha)
        bar_color = (r, g, b, alpha)

        radius = max(1, min(bar_w / 2, 3))

        # 向上的條
        draw.rounded_rectangle(
            [x, center_y - bar_h, x + bar_w, center_y - 1],
            radius=radius, fill=bar_color
        )
        # 向下的條（鏡像）
        draw.rounded_rectangle(
            [x, center_y + 1, x + bar_w, center_y + bar_h],
            radius=radius, fill=bar_color
        )

        # 頂端高亮（上方）
        hl_alpha = int(val * 180)
        hl = (255, 255, 255, hl_alpha)
        hl_h = max(1, 2)
        draw.rectangle(
            [x, center_y - bar_h, x + bar_w, center_y - bar_h + hl_h],
            fill=hl
        )
        # 底端高亮（下方鏡像）
        draw.rectangle(
            [x, center_y + bar_h - hl_h, x + bar_w, center_y + bar_h],
            fill=hl
        )

        # 發光層
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gc = (r, g, b, int(val * 80))
            pad = 2
            gd.rounded_rectangle(
                [x - pad, center_y - bar_h - pad, x + bar_w + pad, center_y + bar_h + pad],
                radius=radius + pad, fill=gc
            )

    # 中線（細微白色橫線）
    line_alpha = 40
    draw.line(
        [(start_x, center_y), (start_x + viz_width, center_y)],
        fill=(255, 255, 255, line_alpha), width=1
    )


# ---------------------------------------------------------------------------
# 繪製：圓環頻譜
# ---------------------------------------------------------------------------

def draw_circular_spectrum(draw, width, height, spectrum, color, glow_layer):
    """圓環頻譜，條狀從圓心向外輻射。"""
    num_bars = len(spectrum)
    cx, cy = width / 2, height / 2
    inner_r = min(width, height) * 0.12
    max_len = min(width, height) * 0.25
    r, g, b = color[0], color[1], color[2]

    for i, val in enumerate(spectrum):
        angle = (i / num_bars) * 2 * math.pi - math.pi / 2
        bar_len = val * max_len
        if bar_len < 2:
            continue

        x1 = cx + math.cos(angle) * inner_r
        y1 = cy + math.sin(angle) * inner_r
        x2 = cx + math.cos(angle) * (inner_r + bar_len)
        y2 = cy + math.sin(angle) * (inner_r + bar_len)

        alpha = int(140 + val * 115)
        lw = max(2, int(2 + val * 3))
        draw.line([x1, y1, x2, y2], fill=(r, g, b, min(255, alpha)), width=lw)

        # 頂端亮點
        dr = lw * 0.6
        draw.ellipse(
            [x2 - dr, y2 - dr, x2 + dr, y2 + dr],
            fill=(255, 255, 255, int(val * 200))
        )

        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.line([x1, y1, x2, y2], fill=(r, g, b, int(val * 60)), width=lw + 6)


# ---------------------------------------------------------------------------
# 繪製：波形線
# ---------------------------------------------------------------------------

def draw_waveform(draw, width, height, spectrum, t, color, glow_layer):
    """上下對稱波形線。"""
    n_pts = 200
    cy = height / 2
    amp = height * 0.30
    mx = width * 0.05
    r, g, b = color[0], color[1], color[2]

    pts_up, pts_dn = [], []
    for i in range(n_pts):
        x = mx + (i / (n_pts - 1)) * (width - 2 * mx)
        si = i / n_pts * (len(spectrum) - 1)
        lo, hi = int(si), min(int(si) + 1, len(spectrum) - 1)
        frac = si - lo
        val = spectrum[lo] * (1 - frac) + spectrum[hi] * frac
        wave = math.sin(i * 0.08 + t * 4.0) * 0.25
        h = (val + wave * val) * amp
        pts_up.append((x, cy - h))
        pts_dn.append((x, cy + h))

    if len(pts_up) > 1:
        draw.line(pts_up, fill=(r, g, b, 200), width=2)
        draw.line(pts_dn, fill=(r, g, b, 200), width=2)
        fill_pts = pts_up + list(reversed(pts_dn))
        if len(fill_pts) >= 3:
            draw.polygon(fill_pts, fill=(r, g, b, 40))
        draw.line(
            [(mx, cy), (width - mx, cy)],
            fill=(255, 255, 255, 60), width=1
        )
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.line(pts_up, fill=(r, g, b, 40), width=8)
            gd.line(pts_dn, fill=(r, g, b, 40), width=8)


# ---------------------------------------------------------------------------
# 渲染引擎
# ---------------------------------------------------------------------------

def render_frame(frame_idx, fps, anim_type, width, height, color,
                 num_bars, bpm, glow, seeds, prev_spectrum, bar_style):
    """渲染單幀，回傳 (RGBA Image, spectrum_data)。"""
    t = frame_idx / fps
    spectrum = generate_spectrum(num_bars, t, bpm, seeds, prev_spectrum)

    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    glow_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0)) if glow else None

    if anim_type == 'bar':
        draw_bar_spectrum(draw, width, height, spectrum, color, glow_layer, bar_style)
    elif anim_type == 'circular':
        draw_circular_spectrum(draw, width, height, spectrum, color, glow_layer)
    elif anim_type == 'wave':
        draw_waveform(draw, width, height, spectrum, t, color, glow_layer)

    if glow and glow_layer is not None:
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
        img = Image.alpha_composite(glow_layer, img)

    return img, spectrum


def encode_to_prores(frames_dir, output_path, fps, width, height):
    """PNG 序列 → ProRes 4444 MOV (含 Alpha)。"""
    cmd = [
        'ffmpeg', '-y',
        '-framerate', str(fps),
        '-i', os.path.join(frames_dir, '%06d.png'),
        '-c:v', 'prores_ks',
        '-profile:v', '4444',
        '-pix_fmt', 'yuva444p10le',
        '-vendor', 'apl0',
        '-s', f'{width}x{height}',
        output_path
    ]
    print(f"\n[編碼] ProRes 4444 MOV...")
    result = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    if result.returncode != 0:
        print(f"[錯誤] FFmpeg 編碼失敗:\n{result.stderr}")
        sys.exit(1)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[完成] {output_path} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='音樂符號律動動畫產生器 — 去背頻譜律動素材 (MOV ProRes 4444)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python generator.py --type bar --style compact --duration 10 --bpm 128
  python generator.py --type bar --style full --color "#FF6B35" --bars 48
  python generator.py --type circular --color "#4ECDC4" --duration 15
  python generator.py --type wave --bpm 90 --color "#FFFFFF"
        """
    )
    parser.add_argument('--type', choices=['bar', 'circular', 'wave'], default='bar',
                        help='動畫類型 (預設: bar)')
    parser.add_argument('--style', choices=['compact', 'full'], default='compact',
                        help='bar 模式的尺寸風格: compact=小型集中(lo-fi風), full=佔滿寬度 (預設: compact)')
    parser.add_argument('--duration', type=float, default=10,
                        help='時長(秒) (預設: 10)')
    parser.add_argument('--fps', type=int, default=30,
                        help='幀率 (預設: 30)')
    parser.add_argument('--width', type=int, default=1920,
                        help='寬度 (預設: 1920)')
    parser.add_argument('--height', type=int, default=1080,
                        help='高度 (預設: 1080)')
    parser.add_argument('--color', type=str, default='#FFFFFF',
                        help='主色調 hex (預設: #FFFFFF 白色)')
    parser.add_argument('--bars', type=int, default=64,
                        help='頻譜條數 (預設: 64)')
    parser.add_argument('--bpm', type=float, default=120,
                        help='BPM 節奏 (預設: 120)')
    parser.add_argument('--output', type=str, default=None,
                        help='輸出檔名 (預設: output_<type>.mov)')
    parser.add_argument('--no-glow', action='store_true',
                        help='關閉發光效果')
    parser.add_argument('--seed', type=int, default=None,
                        help='隨機種子')

    args = parser.parse_args()

    if args.output is None:
        args.output = f'output_{args.type}.mov'

    if shutil.which('ffmpeg') is None:
        print("[錯誤] 找不到 FFmpeg！請安裝並加入 PATH。")
        print("  https://ffmpeg.org/download.html")
        sys.exit(1)

    color = hex_to_rgba(args.color)
    if args.seed is not None:
        np.random.seed(args.seed)
    seeds = np.random.uniform(0, 100, args.bars)
    total = int(args.duration * args.fps)
    glow = not args.no_glow

    print("=" * 55)
    print("  音樂符號律動動畫產生器")
    print("=" * 55)
    print(f"  類型 : {args.type} ({args.style})")
    print(f"  解析度 : {args.width}x{args.height}")
    print(f"  時長 : {args.duration}s ({total} 幀 @ {args.fps}fps)")
    print(f"  BPM  : {args.bpm}")
    print(f"  條數 : {args.bars}")
    print(f"  色調 : {args.color}")
    print(f"  發光 : {'開' if glow else '關'}")
    print(f"  輸出 : {args.output}")
    print("=" * 55)

    tmp_dir = tempfile.mkdtemp(prefix='music_viz_')
    frames_dir = os.path.join(tmp_dir, 'frames')
    os.makedirs(frames_dir)

    try:
        prev = None
        for i in range(total):
            img, prev = render_frame(
                i, args.fps, args.type, args.width, args.height,
                color, args.bars, args.bpm, glow, seeds, prev, args.style
            )
            img.save(os.path.join(frames_dir, f'{i:06d}.png'), 'PNG')

            if (i + 1) % args.fps == 0 or i == total - 1:
                pct = (i + 1) / total * 100
                print(f"\r[渲染] {i+1}/{total} ({pct:.0f}%)", end='', flush=True)

        print()
        output_path = os.path.abspath(args.output)
        encode_to_prores(frames_dir, output_path, args.fps, args.width, args.height)

    finally:
        print("[清理] 移除暫存...")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n[完成] 透明影片已產生，可直接匯入剪輯軟體疊加使用！")


if __name__ == '__main__':
    main()
