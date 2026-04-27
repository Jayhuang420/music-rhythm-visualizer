"""
產生 15 個動畫類型的預覽 GIF
build 時預先渲染，包進 Docker image
"""
import os
import numpy as np
from PIL import Image

from generator import render_frame, hex_to_rgba


OUT_DIR = "previews"
os.makedirs(OUT_DIR, exist_ok=True)

# 預覽尺寸（小一點以縮小檔案）
W, H = 360, 200
FPS = 15
DURATION = 2.4  # 兩秒多 → 包含一個完整 BPM 週期
TOTAL_FRAMES = int(FPS * DURATION)
COLOR = hex_to_rgba("#00ffaa")  # 預覽用螢光綠（與品牌色一致）
BPM = 120
NUM_BARS = 48
BG_COLOR = (15, 15, 30, 255)  # 深色背景以模擬剪輯軟體

TYPES = [
    "dots", "bar", "circular", "wave",
    "pulse_ring", "bouncing_balls", "particle_burst", "vinyl",
    "mountain", "ripple", "starburst", "retro_grid",
    "trail", "scrolling_line", "grid_matrix",
]


def make_gif(anim_type: str):
    np.random.seed(42)
    seeds = np.random.uniform(0, 100, NUM_BARS)

    frames = []
    prev = None
    for i in range(TOTAL_FRAMES):
        img, prev = render_frame(
            i, FPS, anim_type, W, H, COLOR,
            NUM_BARS, BPM, True, seeds, prev, "compact"
        )
        # 疊深色底
        bg = Image.new("RGBA", (W, H), BG_COLOR)
        bg = Image.alpha_composite(bg, img)
        # 縮減顏色以壓縮 GIF
        p_img = bg.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=96)
        frames.append(p_img)

    out_path = os.path.join(OUT_DIR, f"{anim_type}.gif")
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / FPS),
        loop=0,
        optimize=True,
    )
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  [OK] {anim_type:18s} {size_kb:6.1f} KB")


def main():
    print("=" * 50)
    print("  渲染 15 款動畫預覽 GIF")
    print("=" * 50)
    for t in TYPES:
        make_gif(t)
    print("=" * 50)
    print(f"  完成 → {OUT_DIR}/")


if __name__ == "__main__":
    main()
