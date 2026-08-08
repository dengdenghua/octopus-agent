"""从 agnes 生成的绿幕章鱼视频中抽帧并抠绿幕，输出透明 PNG 序列。

用法:
    python extract_frames.py <video_path> <out_dir> [--step N] [--tolerance T]

- --step: 每隔 N 帧取一帧（默认 3，约 8fps）
- --tolerance: 绿幕判定容差（默认 45）
"""
import argparse
import os

import cv2
import numpy as np


def chroma_key(frame: np.ndarray, tolerance: float = 45.0) -> np.ndarray:
    """把纯绿幕背景抠成透明，返回 BGRA 图像。"""
    bgr = frame.astype(np.float32)
    b, g, r = bgr[..., 0], bgr[..., 1], bgr[..., 2]
    # 绿色通道显著高于红/蓝 ===> 判定为背景；背景置透明(0)，前景保留(255)
    greenness = g - np.maximum(r, b)
    mask = ~(greenness > tolerance)
    mask = mask.astype(np.uint8) * 255
    # 轻微开闭运算去噪
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    # 边缘柔化（羽化），避免抠图出现硬边
    mask = cv2.GaussianBlur(mask, (5, 5), 0)

    bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    bgra[..., 3] = mask
    return bgra


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("out_dir")
    parser.add_argument("--step", type=int, default=3)
    parser.add_argument("--tolerance", type=float, default=45.0)
    parser.add_argument("--auto-crop", action="store_true",
                        help="裁剪到章鱼的包围盒，居中")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    saved = 0
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % args.step == 0:
            bgra = chroma_key(frame, args.tolerance)
            if args.auto_crop:
                # 依据 alpha 求包围盒并裁剪 + 生成居中
                ys, xs = np.where(bgra[..., 3] > 8)
                if len(xs) and len(ys):
                    x0, x1 = xs.min(), xs.max()
                    y0, y1 = ys.min(), ys.max()
                    pad = 8
                    x0, x1 = max(0, x0 - pad), min(bgra.shape[1], x1 + pad)
                    y0, y1 = max(0, y0 - pad), min(bgra.shape[0], y1 + pad)
                    bgra = bgra[y0:y1, x0:x1]
            out = os.path.join(args.out_dir, f"frame_{saved:03d}.png")
            cv2.imwrite(out, bgra)
            saved += 1
        frame_idx += 1
    cap.release()
    print(f"done: saved {saved} frames from {total} -> {args.out_dir}")


if __name__ == "__main__":
    main()