#!/usr/bin/env python3
"""
音樂符號律動動畫產生器
======================
隨機產生頻譜波形律動動畫，輸出為去背 MOV (ProRes 4444) 透明影片素材。
參考風格：lo-fi 音樂頻道常見的纖細鏡像直條頻譜。

支援 14 種動畫類型：
  原始 4 款：
  - bar             : 鏡像直條頻譜（lo-fi 風格）
  - circular        : 圓環頻譜
  - wave            : 波形線
  - dots            : 底部點陣律動

  YT 流行款 10 款：
  - pulse_ring      : 脈衝光環（同心圓擴散）
  - bouncing_balls  : 彈跳小球
  - particle_burst  : 粒子爆發
  - vinyl           : 黑膠唱片旋轉
  - mountain        : 山形頻譜剪影
  - ripple          : 水波紋擴散
  - starburst       : 星芒散射
  - retro_grid      : 80s synthwave 透視網格
  - trail           : 拖尾彗星繞圈
  - scrolling_line  : 滾動心電圖
  - grid_matrix     : LED 方塊矩陣
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
# 繪製：底部點陣律動（YouTube 影片底部常見橫排圓點頻譜）
# ---------------------------------------------------------------------------

def draw_dots_spectrum(draw, width, height, spectrum, t, color, glow_layer):
    """
    橫排圓點頻譜：點陣沿底部水平排列，每個點的大小與亮度跟隨頻譜值跳動。
    模擬 YouTube 音樂影片底部常見的點狀律動動畫。
    """
    num_dots = len(spectrum)
    r, g, b = color[0], color[1], color[2]

    # 佈局：橫排佔畫面寬度 80%，位置在畫面下方 12% 處
    row_width = width * 0.80
    start_x = (width - row_width) / 2
    base_y = height * 0.88

    dot_spacing = row_width / num_dots
    max_radius = dot_spacing * 0.42
    min_radius = max_radius * 0.25

    # 整體呼吸脈衝（全部點一起微微放大）
    pulse = beat_pulse(t, 120) * 0.15

    for i, val in enumerate(spectrum):
        cx = start_x + i * dot_spacing + dot_spacing / 2
        radius = min_radius + (max_radius - min_radius) * (val + pulse)
        radius = max(min_radius * 0.5, min(max_radius * 1.15, radius))

        # 透明度：最低點半透明，最高點不透明
        base_alpha = 60
        alpha = int(base_alpha + (255 - base_alpha) * val)
        alpha = min(255, alpha)

        dot_color = (r, g, b, alpha)
        draw.ellipse(
            [cx - radius, base_y - radius, cx + radius, base_y + radius],
            fill=dot_color
        )

        # 頂部高光（小白點讓圓點有立體感）
        hl_r = radius * 0.3
        hl_alpha = int(val * 160)
        draw.ellipse(
            [cx - hl_r * 0.6, base_y - radius * 0.55 - hl_r * 0.6,
             cx + hl_r * 0.6, base_y - radius * 0.55 + hl_r * 0.6],
            fill=(255, 255, 255, hl_alpha)
        )

        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gr = radius + 4
            gd.ellipse(
                [cx - gr, base_y - gr, cx + gr, base_y + gr],
                fill=(r, g, b, int(val * 70))
            )

    # 細橫線連結所有點（半透明，增加整體感）
    line_y = base_y
    draw.line(
        [(start_x + dot_spacing / 2, line_y),
         (start_x + row_width - dot_spacing / 2, line_y)],
        fill=(r, g, b, 25), width=1
    )


# ---------------------------------------------------------------------------
# 繪製：脈衝光環 (Pulse Ring) — 拍點同心圓擴散
# ---------------------------------------------------------------------------

def draw_pulse_ring(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """多重同心圓在拍點觸發向外擴散，常見於 lo-fi 頻道。"""
    cx, cy = width / 2, height / 2
    r, g, b = color[0], color[1], color[2]
    max_r = min(width, height) * 0.42
    energy = float(np.mean(spectrum))

    # 4 圈獨立週期錯開
    for k in range(4):
        phase = ((t * bpm / 60.0 / 2.0) + k * 0.25) % 1.0
        radius = phase * max_r
        if radius < 6:
            continue
        alpha = int((1.0 - phase) * 200 * (0.5 + energy))
        alpha = max(0, min(220, alpha))
        lw = max(2, int(4 + (1.0 - phase) * 4))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(r, g, b, alpha), width=lw
        )
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=(r, g, b, alpha // 2), width=lw + 6
            )

    # 中心固定圓點
    pulse = beat_pulse(t, bpm)
    cr = 8 + pulse * 14
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr],
                 fill=(r, g, b, 200))


# ---------------------------------------------------------------------------
# 繪製：彈跳小球 (Bouncing Balls)
# ---------------------------------------------------------------------------

def draw_bouncing_balls(draw, width, height, spectrum, t, color, glow_layer):
    """一排小球隨頻譜上下彈跳，地面有反射。"""
    n = min(len(spectrum), 24)
    r, g, b = color[0], color[1], color[2]
    row_w = width * 0.7
    start_x = (width - row_w) / 2
    base_y = height * 0.75
    spacing = row_w / n
    radius = max(6, spacing * 0.22)
    bounce_h = height * 0.35

    for i in range(n):
        val = spectrum[i * len(spectrum) // n]
        x = start_x + i * spacing + spacing / 2
        # |sin| 模擬彈跳
        bounce = abs(math.sin(t * 4 + i * 0.4)) * val
        y = base_y - bounce * bounce_h
        alpha = int(180 + val * 75)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius],
                     fill=(r, g, b, alpha))
        # 陰影 (地面)
        sh_w = radius * (1.4 - bounce * 0.6)
        sh_alpha = int(120 * (1.0 - bounce))
        draw.ellipse([x - sh_w, base_y - 3, x + sh_w, base_y + 3],
                     fill=(r, g, b, sh_alpha))
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gr = radius + 5
            gd.ellipse([x - gr, y - gr, x + gr, y + gr],
                       fill=(r, g, b, int(val * 90)))


# ---------------------------------------------------------------------------
# 繪製：粒子爆發 (Particle Burst)
# ---------------------------------------------------------------------------

def draw_particle_burst(draw, width, height, spectrum, t, color, seeds, glow_layer, bpm):
    """從中心向四面八方爆射粒子，拍點時亮度增強。"""
    cx, cy = width / 2, height / 2
    r, g, b = color[0], color[1], color[2]
    max_r = min(width, height) * 0.4
    pulse = beat_pulse(t, bpm)
    n_particles = min(len(seeds), 80)

    for i in range(n_particles):
        s = seeds[i]
        angle = (s / 100.0) * 2 * math.pi
        speed = 0.5 + (s % 7) / 10.0
        phase = ((t * speed) + s * 0.13) % 1.0
        dist = phase * max_r
        x = cx + math.cos(angle) * dist
        y = cy + math.sin(angle) * dist
        size = max(1, (1 - phase) * 4 + pulse * 3)
        alpha = int((1 - phase) * 220 + pulse * 35)
        alpha = min(255, alpha)
        draw.ellipse([x - size, y - size, x + size, y + size],
                     fill=(r, g, b, alpha))
        if glow_layer is not None and phase < 0.6:
            gd = ImageDraw.Draw(glow_layer)
            gs = size + 3
            gd.ellipse([x - gs, y - gs, x + gs, y + gs],
                       fill=(r, g, b, alpha // 3))

    # 中央亮點
    cr = 6 + pulse * 14
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr],
                 fill=(255, 255, 255, 230))


# ---------------------------------------------------------------------------
# 繪製：黑膠唱片 (Vinyl Record)
# ---------------------------------------------------------------------------

def draw_vinyl(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """旋轉黑膠唱片，外圈分段亮度跟隨頻譜。"""
    cx, cy = width / 2, height / 2
    r_outer = min(width, height) * 0.35
    r_inner = r_outer * 0.18
    r, g, b = color[0], color[1], color[2]
    n_seg = min(len(spectrum), 64)
    rot = t * 0.6  # 緩慢旋轉

    # 唱片底盤 (細圈紋)
    for k in range(6):
        rr = r_inner + (r_outer - r_inner) * (k + 1) / 7
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                     outline=(r, g, b, 50), width=1)

    # 外圈分段頻譜 (沿圓周)
    for i in range(n_seg):
        val = spectrum[i * len(spectrum) // n_seg]
        a1 = (i / n_seg) * 2 * math.pi + rot
        a2 = ((i + 1) / n_seg) * 2 * math.pi + rot
        a_mid = (a1 + a2) / 2
        seg_len = val * r_outer * 0.35
        x1 = cx + math.cos(a_mid) * r_outer
        y1 = cy + math.sin(a_mid) * r_outer
        x2 = cx + math.cos(a_mid) * (r_outer + seg_len)
        y2 = cy + math.sin(a_mid) * (r_outer + seg_len)
        alpha = int(150 + val * 105)
        lw = max(2, int(3 + val * 4))
        draw.line([x1, y1, x2, y2], fill=(r, g, b, alpha), width=lw)

    # 中央標籤
    draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
                 fill=(r, g, b, 160))
    # 中央小孔
    rh = r_inner * 0.18
    draw.ellipse([cx - rh, cy - rh, cx + rh, cy + rh],
                 fill=(0, 0, 0, 0))

    if glow_layer is not None:
        gd = ImageDraw.Draw(glow_layer)
        gd.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
                   outline=(r, g, b, 80), width=10)


# ---------------------------------------------------------------------------
# 繪製：山形頻譜 (Mountain)
# ---------------------------------------------------------------------------

def draw_mountain(draw, width, height, spectrum, color, glow_layer):
    """頻譜連線後填滿，模擬山稜剪影。"""
    n = len(spectrum)
    r, g, b = color[0], color[1], color[2]
    base_y = height * 0.78
    peak_h = height * 0.55
    margin = width * 0.06
    seg_w = (width - margin * 2) / (n - 1)

    pts = []
    for i, val in enumerate(spectrum):
        x = margin + i * seg_w
        y = base_y - val * peak_h
        pts.append((x, y))

    # 填滿多邊形
    fill_pts = pts + [(width - margin, base_y), (margin, base_y)]
    draw.polygon(fill_pts, fill=(r, g, b, 70))
    # 山稜線
    draw.line(pts, fill=(r, g, b, 230), width=3)
    # 底邊
    draw.line([(margin, base_y), (width - margin, base_y)],
              fill=(r, g, b, 80), width=1)

    if glow_layer is not None:
        gd = ImageDraw.Draw(glow_layer)
        gd.line(pts, fill=(r, g, b, 60), width=10)


# ---------------------------------------------------------------------------
# 繪製：水波紋 (Ripple)
# ---------------------------------------------------------------------------

def draw_ripple(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """從中心向外擴散的水波紋，拍點時觸發新波。"""
    cx, cy = width / 2, height / 2
    r, g, b = color[0], color[1], color[2]
    max_r = min(width, height) * 0.45
    energy = float(np.mean(spectrum))
    period = 60.0 / bpm * 2

    for k in range(5):
        phase = ((t / period) + k * 0.2) % 1.0
        radius = phase * max_r
        if radius < 4:
            continue
        # 波形外圈+漸淡
        fade = (1.0 - phase) ** 2
        alpha = int(220 * fade * (0.5 + energy * 0.8))
        lw = max(1, int(2 + fade * 3))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(r, g, b, alpha), width=lw
        )
        # 內側淡波
        radius2 = radius - lw - 4
        if radius2 > 4:
            draw.ellipse(
                [cx - radius2, cy - radius2, cx + radius2, cy + radius2],
                outline=(r, g, b, alpha // 3), width=1
            )
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=(r, g, b, alpha // 3), width=lw + 5
            )


# ---------------------------------------------------------------------------
# 繪製：星芒散射 (Starburst)
# ---------------------------------------------------------------------------

def draw_starburst(draw, width, height, spectrum, color, glow_layer):
    """從中心向各方向散射的線，線長隨頻譜。"""
    cx, cy = width / 2, height / 2
    r, g, b = color[0], color[1], color[2]
    n_rays = len(spectrum)
    max_len = min(width, height) * 0.42

    for i, val in enumerate(spectrum):
        angle = (i / n_rays) * 2 * math.pi
        ray_len = val * max_len
        x2 = cx + math.cos(angle) * ray_len
        y2 = cy + math.sin(angle) * ray_len
        alpha = int(150 + val * 105)
        lw = max(1, int(1 + val * 3))
        # 漸層用兩段線
        x_mid = cx + math.cos(angle) * ray_len * 0.4
        y_mid = cy + math.sin(angle) * ray_len * 0.4
        draw.line([cx, cy, x_mid, y_mid], fill=(r, g, b, alpha), width=lw)
        draw.line([x_mid, y_mid, x2, y2],
                  fill=(r, g, b, max(40, alpha - 80)), width=lw)
        # 末端亮點
        dr = max(1, lw)
        draw.ellipse([x2 - dr, y2 - dr, x2 + dr, y2 + dr],
                     fill=(255, 255, 255, int(val * 200)))
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.line([cx, cy, x2, y2], fill=(r, g, b, int(val * 60)), width=lw + 4)


# ---------------------------------------------------------------------------
# 繪製：復古網格 (Retro Grid - synthwave)
# ---------------------------------------------------------------------------

def draw_retro_grid(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """80s synthwave 透視網格，向遠方延伸。"""
    r, g, b = color[0], color[1], color[2]
    horizon = height * 0.5
    bottom = height * 0.95
    pulse = beat_pulse(t, bpm)
    energy = float(np.mean(spectrum))

    # 水平線（往遠方逐漸密集）
    n_h = 8
    scroll = (t * 0.5) % 1.0  # 滾動
    for i in range(n_h):
        prog = (i + scroll) / n_h
        # 透視：靠近底部更稀疏，靠近 horizon 更密集
        y = horizon + (bottom - horizon) * (prog ** 1.6)
        if y > horizon and y < bottom:
            alpha = int(160 * (1 - prog) + pulse * 50)
            draw.line([(0, y), (width, y)], fill=(r, g, b, alpha), width=2)

    # 垂直線（透視收斂到 horizon 中心）
    cx = width / 2
    n_v = 11
    for i in range(n_v):
        x_bot = (i / (n_v - 1)) * width
        # 收斂到 cx
        for k in range(20):
            t1 = k / 20
            t2 = (k + 1) / 20
            x1 = x_bot * (1 - t1) + cx * t1
            y1 = bottom * (1 - t1) + horizon * t1
            x2 = x_bot * (1 - t2) + cx * t2
            y2 = bottom * (1 - t2) + horizon * t2
            alpha = int(180 * (1 - t1))
            draw.line([(x1, y1), (x2, y2)], fill=(r, g, b, alpha), width=1)

    # 太陽（horizon 上方圓）
    sun_r = min(width, height) * 0.12 * (1 + pulse * 0.1 + energy * 0.15)
    sun_y = horizon - sun_r * 0.5
    draw.ellipse([cx - sun_r, sun_y - sun_r, cx + sun_r, sun_y + sun_r],
                 fill=(r, g, b, 220))
    # 太陽橫切線
    for k in range(6):
        ly = sun_y + sun_r * 0.2 + k * sun_r * 0.18
        if ly < sun_y + sun_r:
            draw.line([(cx - sun_r, ly), (cx + sun_r, ly)],
                      fill=(0, 0, 0, 200), width=max(2, int(sun_r * 0.06)))

    if glow_layer is not None:
        gd = ImageDraw.Draw(glow_layer)
        gd.ellipse([cx - sun_r, sun_y - sun_r, cx + sun_r, sun_y + sun_r],
                   fill=(r, g, b, 80))


# ---------------------------------------------------------------------------
# 繪製：拖尾彗星 (Trail / Comet)
# ---------------------------------------------------------------------------

def draw_trail(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """光點繞圓圈轉，後方拖尾漸淡。"""
    cx, cy = width / 2, height / 2
    r, g, b = color[0], color[1], color[2]
    orbit_r = min(width, height) * 0.32
    energy = float(np.mean(spectrum))
    pulse = beat_pulse(t, bpm)
    speed = 0.8 + energy * 0.6

    n_trail = 30
    for k in range(n_trail):
        ang = (t * speed - k * 0.06) * 2 * math.pi / 4
        x = cx + math.cos(ang) * orbit_r
        y = cy + math.sin(ang) * orbit_r
        fade = 1.0 - k / n_trail
        size = max(1, fade * (8 + pulse * 5))
        alpha = int(fade * 230)
        draw.ellipse([x - size, y - size, x + size, y + size],
                     fill=(r, g, b, alpha))
        if glow_layer is not None and k < 10:
            gd = ImageDraw.Draw(glow_layer)
            gs = size + 6
            gd.ellipse([x - gs, y - gs, x + gs, y + gs],
                       fill=(r, g, b, alpha // 3))

    # 軌道虛線
    for k in range(48):
        ang = (k / 48) * 2 * math.pi
        x = cx + math.cos(ang) * orbit_r
        y = cy + math.sin(ang) * orbit_r
        draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(r, g, b, 50))


# ---------------------------------------------------------------------------
# 繪製：滾動心電圖 (Scrolling EKG Line)
# ---------------------------------------------------------------------------

def draw_scrolling_line(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """類似心電圖的水平滾動線，拍點時尖峰上跳。"""
    r, g, b = color[0], color[1], color[2]
    cy = height / 2
    amp = height * 0.28
    n_pts = 400

    pts = []
    for i in range(n_pts):
        x = (i / (n_pts - 1)) * width
        # 該點對應的時間（從右到左移動）
        local_t = t - (n_pts - 1 - i) * 0.012
        if local_t < 0:
            pts.append((x, cy))
            continue
        # 尖峰：每拍出現一個 EKG 樣式的尖峰
        beat_phase = (local_t * bpm / 60.0) % 1.0
        spike = 0.0
        if beat_phase < 0.06:
            spike = math.sin(beat_phase / 0.06 * math.pi) * 1.0
        elif beat_phase < 0.10:
            spike = -math.sin((beat_phase - 0.06) / 0.04 * math.pi) * 0.45
        # 細微噪聲
        si = int((i / n_pts) * len(spectrum)) % len(spectrum)
        noise_val = (spectrum[si] - 0.3) * 0.08
        y = cy - (spike + noise_val) * amp
        pts.append((x, y))

    if len(pts) >= 2:
        draw.line(pts, fill=(r, g, b, 230), width=2)
        # 當前位置標記 (右側亮點)
        draw.ellipse([width - 8, pts[-1][1] - 4, width, pts[-1][1] + 4],
                     fill=(255, 255, 255, 230))
        if glow_layer is not None:
            gd = ImageDraw.Draw(glow_layer)
            gd.line(pts, fill=(r, g, b, 60), width=8)


# ---------------------------------------------------------------------------
# 繪製：方塊矩陣 (Grid Matrix)
# ---------------------------------------------------------------------------

def draw_grid_matrix(draw, width, height, spectrum, t, color, glow_layer, bpm):
    """方塊矩陣 LED 風格，亮度跟隨頻譜。"""
    r, g, b = color[0], color[1], color[2]
    cols = 16
    rows = 8
    panel_w = width * 0.6
    panel_h = height * 0.35
    px = (width - panel_w) / 2
    py = (height - panel_h) / 2
    cell_w = panel_w / cols
    cell_h = panel_h / rows
    pulse = beat_pulse(t, bpm)

    for c in range(cols):
        # 用頻譜值決定該欄高度
        val = spectrum[c * len(spectrum) // cols]
        lit_rows = int(val * rows + pulse * 1.5)
        for rr in range(rows):
            cx_ = px + c * cell_w + cell_w * 0.1
            cy_ = py + (rows - 1 - rr) * cell_h + cell_h * 0.1
            cw = cell_w * 0.8
            ch = cell_h * 0.8
            if rr < lit_rows:
                # 已點亮：頂端漸淡
                fade = 1.0 - rr / max(1, lit_rows)
                alpha = int(120 + fade * 135)
                draw.rectangle([cx_, cy_, cx_ + cw, cy_ + ch],
                               fill=(r, g, b, alpha))
                if glow_layer is not None and rr < 3:
                    gd = ImageDraw.Draw(glow_layer)
                    gd.rectangle([cx_ - 2, cy_ - 2, cx_ + cw + 2, cy_ + ch + 2],
                                 fill=(r, g, b, int(fade * 100)))
            else:
                # 未點亮：暗格
                draw.rectangle([cx_, cy_, cx_ + cw, cy_ + ch],
                               fill=(r, g, b, 22))


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
    elif anim_type == 'dots':
        draw_dots_spectrum(draw, width, height, spectrum, t, color, glow_layer)
    elif anim_type == 'pulse_ring':
        draw_pulse_ring(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'bouncing_balls':
        draw_bouncing_balls(draw, width, height, spectrum, t, color, glow_layer)
    elif anim_type == 'particle_burst':
        draw_particle_burst(draw, width, height, spectrum, t, color, seeds, glow_layer, bpm)
    elif anim_type == 'vinyl':
        draw_vinyl(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'mountain':
        draw_mountain(draw, width, height, spectrum, color, glow_layer)
    elif anim_type == 'ripple':
        draw_ripple(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'starburst':
        draw_starburst(draw, width, height, spectrum, color, glow_layer)
    elif anim_type == 'retro_grid':
        draw_retro_grid(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'trail':
        draw_trail(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'scrolling_line':
        draw_scrolling_line(draw, width, height, spectrum, t, color, glow_layer, bpm)
    elif anim_type == 'grid_matrix':
        draw_grid_matrix(draw, width, height, spectrum, t, color, glow_layer, bpm)

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
    parser.add_argument('--type', choices=[
        'bar', 'circular', 'wave', 'dots',
        'pulse_ring', 'bouncing_balls', 'particle_burst', 'vinyl',
        'mountain', 'ripple', 'starburst', 'retro_grid',
        'trail', 'scrolling_line', 'grid_matrix',
    ], default='bar', help='動畫類型 (預設: bar)')
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
