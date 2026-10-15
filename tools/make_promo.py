"""Render the product film from checked-in screenshots; Pillow and FFmpeg required.

No network calls, UI automation, stock music or generated product mockups.
Example: python tools/make_promo.py --output dist/media --font /path/to/CJK-font.ttc
"""
from pathlib import Path
import argparse
import array
import hashlib
import json
import math
import shutil
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1920, 1080)
BG = (26, 32, 27)
GOLD = (223, 183, 110)
WHITE = (247, 243, 229)
MUTED = (174, 184, 167)
# All footage is a composition of actual product captures, using a demonstration save.
SCENES = (
    ("intro", 6), ("companion", 10), ("library", 9),
    ("planning", 9), ("alchemy", 8), ("history", 8), ("outro", 8),
)


def run(command):
    subprocess.run(command, check=True)


def soundtrack(path, seconds):
    """Original quiet pentatonic motif, synthesized here with no sampled audio."""
    rate = 44100
    notes = (196.0, 246.94, 293.66, 369.99, 392.0, 329.63, 293.66, 246.94)
    with wave.open(str(path), 'wb') as output:
        output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        for second in range(seconds):
            data = array.array('h')
            for n in range(rate):
                t = second + n / rate
                age = t % 0.75
                note = notes[int(t / 0.75) % len(notes)]
                envelope = (1 - math.exp(-age * 32)) * math.exp(-age * 4)
                bell = (math.sin(2 * math.pi * note * t)
                        + 0.25 * math.sin(2 * math.pi * note * 2 * t)) * envelope
                pad = (math.sin(2 * math.pi * 98 * t)
                       + math.sin(2 * math.pi * 146.83 * t)) * 0.12
                fade = min(1, t / 2, (seconds - t) / 3)
                sample = int(2900 * (bell + pad) * max(0, fade))
                data.extend((sample, sample))
            # WAV stores little endian regardless of the host.
            import sys
            if sys.byteorder != 'little':
                data.byteswap()
            output.writeframes(data.tobytes())


def render_scene(name, folder, font_path):
    image = Image.new('RGB', SIZE, BG)
    draw = ImageDraw.Draw(image)
    def text(x, y, value, size, color=WHITE):
        draw.text((x, y), value, font=ImageFont.truetype(str(font_path), size), fill=color)
    if name in ('intro', 'outro'):
        logo = Image.open(ROOT / 'data/lamp.png').convert('RGBA').resize((180, 180), Image.Resampling.NEAREST)
        image.paste(logo, (870, 160), logo)
        text(804, 390, '灯火', 150)
        if name == 'intro':
            text(462, 640, '把地牢里的关键选择，看得更清楚。', 52)
            text(674, 757, '破碎的像素地牢 · Windows 随行助手', 29, MUTED)
        else:
            text(536, 626, '下地牢之前，点一盏灯。', 66)
            text(538, 750, 'github.com/Legender134/denghuo', 42, GOLD)
            text(618, 850, 'Windows 10 / 11 x64 · 开源 · 中文', 32, MUTED)
            text(457, 980, '独立开源项目 · 非游戏官方产品 · 游戏图像版权归原作者', 25, MUTED)
    else:
        source = Image.open(ROOT / 'docs/images' / (name + '.png')).convert('RGB')
        # Retain captions and complete photo framing; no misleading crop of conditions.
        source.thumbnail((1760, 1010), Image.Resampling.LANCZOS)
        image.paste(source, ((SIZE[0]-source.width)//2, (SIZE[1]-source.height)//2))
    path = folder / (name + '.png')
    image.save(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font', type=Path, default=Path('C:/Windows/Fonts/msyh.ttc'))
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--preview-only', action='store_true')
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error('Supply --font with an installed Chinese font file.')
    if not args.preview_only and not shutil.which(args.ffmpeg):
        parser.error('FFmpeg is required; install it separately or use --ffmpeg.')
    folder = args.output.resolve()
    # Never overwrite an existing render, its inputs or evidence.
    folder.mkdir(parents=True, exist_ok=False)
    source_paths = [ROOT / 'data/lamp.png'] + [ROOT / 'docs/images' / (n + '.png') for n, _ in SCENES if n not in ('intro', 'outro')]
    for path in source_paths:
        if not path.is_file():
            parser.error('Missing input: ' + str(path))
    clips = []
    for name, duration in SCENES:
        frame = render_scene(name, folder, args.font)
        if args.preview_only:
            continue
        clip = folder / (name + '.mp4')
        frames = duration * 30
        # Gentle camera drift and short fades; screenshots remain readable.
        vf = (f"zoompan=z='1+0.018*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
              f"d={frames}:s=1920x1080:fps=30,fade=t=in:st=0:d=0.32,"
              f"fade=t=out:st={duration-0.32}:d=0.32,format=yuv420p")
        run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(frame),
             '-vf', vf, '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'fast',
             '-crf', '19', '-threads', '4', '-an', str(clip)])
        clips.append(clip)
    if args.preview_only:
        return
    audio = folder / 'original-score.wav'
    soundtrack(audio, sum(length for _, length in SCENES))
    listing = folder / 'clips.txt'
    # The fixed relative names above contain no quoting or path metacharacters.
    listing.write_text(''.join("file '" + clip.name + "'\n" for clip in clips), encoding='utf-8')
    video = folder / 'denghuo-introduction-0.7.0.mp4'
    run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '1',
         '-i', str(listing), '-i', str(audio), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
         '-shortest', '-movflags', '+faststart', str(video)])
    receipt = {'video': video.name, 'duration_seconds': sum(d for _, d in SCENES),
               'size': SIZE, 'fps': 30, 'audio': 'Original motif synthesized by this script; no voiceover',
               'inputs': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
               'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest()}
    (folder / 'render.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
