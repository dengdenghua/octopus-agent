"""把抽帧得到的透明 PNG 序列合成一张横向精灵图集（spritesheet）。

用法:
    python make_sheet.py <frames_dir> <out_path> [--cols N] [--scale S]
"""
import argparse
import glob
import os

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir")
    parser.add_argument("out_path")
    parser.add_argument("--cols", type=int, default=0,
                        help="每行帧数，0=全部排成一行")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="缩放比例，用于缩小图集体积")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.frames_dir, "*.png")))
    if not files:
        raise SystemExit(f"no png in {args.frames_dir}")
    frames = [Image.open(f).convert("RGBA") for f in files]
    if args.scale != 1.0:
        frames = [
            f.resize((int(f.width * args.scale), int(f.height * args.scale)),
                     Image.LANCZOS)
            for f in frames
        ]
    w, h = frames[0].size
    cols = args.cols or len(frames)
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * w, rows * h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i % cols * w, i // cols * h))
    os.makedirs(os.path.dirname(args.out_path) or ".", exist_ok=True)
    sheet.save(args.out_path)
    print(f"sheet: {cols}x{rows}, cell={w}x{h}, frames={len(frames)} -> {args.out_path}")


if __name__ == "__main__":
    main()