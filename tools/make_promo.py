"""Edit the 36-second Denghuo film from real screen recordings.

Python 3.10+, Pillow, NumPy, FFmpeg and an installed Chinese font are required.
Download the footage archive linked in docs/media.md, then run:
  python tools/make_promo.py --footage footage/manifest.json --output dist/film
No network, UI automation, stock audio, or reconstructed product screens.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIZE, FPS = (1920, 1080), 30
GOLD, WHITE, MUTED = (230, 187, 117), (244, 242, 229), (167, 180, 163)
SCENES = (('game', 3.5), ('problem', 4), ('reason', 2.5), ('open', 3),
          ('edit', 3), ('calculate', 3), ('result', 5), ('collapse', 3),
          ('expand', 3), ('outro', 6))
DURATION = sum(d for _, d in SCENES)


def ease(v):
    v = max(0.0, min(1.0, v))
    return v * v * (3 - 2 * v)


def pose(a, b, v):
    return tuple(x + (y - x) * ease(v) for x, y in zip(a, b))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def load_footage(path):
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('format') != 1: raise ValueError('Unsupported footage manifest.')
    result = {}
    for name, duration in SCENES:
        item = document['takes'][name]
        source = (path.parent / item['file']).resolve()
        if not source.is_relative_to(path.parent.resolve()) or not source.is_file():
            raise ValueError('Footage must be inside the manifest directory: ' + name)
        if abs(item['duration'] - duration) > .001 or digest(source) != item['sha256']:
            raise ValueError('Footage duration/hash does not match: ' + name)
        result[name] = {**item, 'path': source}
    return result


class Reader:
    """Sequential real frames, without still substitutes or hidden looping."""
    def __init__(self, ffmpeg, item):
        self.size = tuple(item['size'])
        self.frame_bytes = self.size[0] * self.size[1] * 3
        self.process = subprocess.Popen(
            [ffmpeg, '-v', 'error', '-i', str(item['path']), '-an', '-vf', f'fps={FPS}',
             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)

    def frame(self):
        data = bytearray()
        while len(data) < self.frame_bytes:
            chunk = self.process.stdout.read(self.frame_bytes - len(data))
            if not chunk: raise RuntimeError('Recording ended before the edit finished.')
            data.extend(chunk)
        return Image.frombytes('RGB', self.size, bytes(data))

    def close(self):
        self.process.stdout.read()
        if self.process.wait() != 0: raise RuntimeError('Could not decode recording.')


class Film:
    def __init__(self, font_path, bold_path):
        self.font_path, self.bold_path = str(font_path), str(bold_path)
        self.fonts, self.texts = {}, {}
        self.logo = Image.open(ROOT / 'data/lamp.png').convert('RGBA')
        yy, xx = np.mgrid[0:1080, 0:1920]
        glow = np.exp(-((xx - 1400) / 800) ** 2 - ((yy - 460) / 730) ** 2)
        grain = np.random.default_rng(203).normal(0, .52, (1080, 1920))
        channels = [16 + glow * 14 + grain, 22 + glow * 14 + grain, 20 + glow * 8 + grain]
        self.base = Image.fromarray(np.clip(np.stack(channels, axis=2), 0, 255).astype('uint8')).convert('RGBA')
        self.shadow = Image.new('RGBA', (900, 1180))
        ImageDraw.Draw(self.shadow).rounded_rectangle((55, 55, 845, 1125), radius=26, fill=(0, 0, 0, 160))
        self.shadow = self.shadow.filter(ImageFilter.GaussianBlur(27))
        self.particles = np.random.default_rng(49).random((35, 4))

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(self.bold_path if bold else self.font_path, size)
        return self.fonts[key]

    def text(self, canvas, value, xy, size, color=WHITE, alpha=1, bold=False):
        key = (value, size, color, bold)
        if key not in self.texts:
            font = self.font(size, bold); box = font.getbbox(value)
            tile = Image.new('RGBA', (box[2] + 8, box[3] - box[1] + 8))
            ImageDraw.Draw(tile).text((0, 2 - box[1]), value, font=font, fill=(*color, 255))
            self.texts[key] = tile
        tile = self.texts[key]
        if alpha < 1:
            tile = tile.copy()
            tile.putalpha(tile.getchannel('A').point(lambda p: int(p * max(0, alpha))))
        canvas.alpha_composite(tile, (round(xy[0]), round(xy[1])))

    def words(self, canvas, lines, t, x=118, y=286, size=86):
        for i, line in enumerate(lines):
            p = ease((t - .13 * i) / .65)
            self.text(canvas, line, (x, y + i * (size + 30) + 52 * (1 - p)),
                      size, GOLD if i == len(lines) - 1 else WHITE, p, True)

    def centered(self, canvas, value, y, size, color=WHITE, alpha=1, bold=False):
        width = self.font(size, bold).getlength(value)
        self.text(canvas, value, ((1920-width)/2, y), size, color, alpha, bold)

    def ambient(self, t):
        c = self.base.copy(); d = ImageDraw.Draw(c, 'RGBA')
        for x, y, speed, radius in self.particles:
            px = int(x * 1920 + 15 * math.sin(t * .25 + y * 12))
            py = int((y * 1200 - t * (5 + speed * 13)) % 1200 - 60)
            r = 1 + radius * 2
            d.ellipse((px-r, py-r, px+r, py+r), fill=(*GOLD, 35))
        d.line((118, 925, 1800, 925), fill=(114, 130, 109, 40), width=1)
        head = 118 + (t * 83) % 1682
        d.line((max(118, head-110), 925, head, 925), fill=(*GOLD, 110), width=2)
        return c

    def chrome(self, c, t, name):
        c.alpha_composite(self.logo.resize((31, 31), Image.Resampling.NEAREST), (118, 65))
        self.text(c, '灯火', (164, 68), 26, WHITE, .9, True)
        label = ('游戏与试算为独立演示' if name == 'game' else
                 '画面合成 · 非同一局' if name in ('collapse','expand') else
                 '游戏实录' if name == 'outro' else '实际录屏 · 独立演示存档')
        self.text(c, label, (1800-self.font(32).getlength(label),68),32,MUTED)
        ImageDraw.Draw(c).line((118, 1000, 118 + (1682 * t / DURATION), 1000), fill=GOLD, width=2)

    def ui(self, c, frame, position, viewport=(825, 120, 1830, 915), crop=None):
        x, y, scale = position
        source = frame.crop(crop) if crop else frame
        w, h = (max(1, round(v * scale)) for v in source.size)
        layer = Image.new('RGBA', SIZE)
        layer.alpha_composite(self.shadow.resize((w + 80, h + 80)), (round(x)-40, round(y)-30))
        layer.alpha_composite(source.resize((w, h), Image.Resampling.LANCZOS).convert('RGBA'), (round(x), round(y)))
        if viewport:
            mask = Image.new('L', SIZE); ImageDraw.Draw(mask).rectangle(viewport, fill=255)
            layer.putalpha(Image.composite(layer.getchannel('A'), Image.new('L', SIZE), mask))
        c.alpha_composite(layer)

    def pointer(self, c, t, at, xy):
        if t < at - .7 or t > at + .5: return
        p = ease((t - at + .7) / .65)
        x, y = xy[0]+110*(1-p), xy[1]+95*(1-p)
        overlay = Image.new('RGBA', SIZE); d = ImageDraw.Draw(overlay)
        if t >= at:
            q = (t - at) / .5; r = 10 + q * 34
            d.ellipse((x-r, y-r, x+r, y+r), outline=(*GOLD, int(220 * (1-q))), width=3)
        d.polygon([(x,y),(x+4,y+27),(x+11,y+19),(x+21,y+20)], fill=(248,246,233,245), outline=(23,29,24,255), width=2)
        c.alpha_composite(overlay)

    def gameplay(self, frame, t, dark=.1):
        z = 1 + .035 * ease(t / 3); w, h = 560 / z, 315 / z
        cx, cy = 477 + 8 * math.sin(t / 3), 300
        frame = frame.crop((int(cx-w/2), int(cy-h/2), int(cx+w/2), int(cy+h/2)))
        c = frame.resize(SIZE, Image.Resampling.NEAREST).convert('RGBA')
        c.alpha_composite(Image.new('RGBA', SIZE, (10, 16, 13, int(dark*255))))
        shade = Image.new('RGBA', (1920, 1))
        shade.putdata([(10,16,13,int(205 * max(0,1-x/1400))) for x in range(1920)])
        c.alpha_composite(shade.resize(SIZE))
        return c

    def render(self, name, frame, t, absolute, game_context=None):
        c = self.ambient(absolute)
        if name == 'game':
            c = self.gameplay(frame,t,.08)
            self.words(c,['再升一级，','力量够吗？'],t-.1,y=340,size=94)
            self.text(c,'下决定之前，先看清条件。',(123,637),32,MUTED,ease((t-.8)/.6))
        elif name == 'problem':
            self.words(c,['先看','卡在哪。'],t,y=295,size=93)
            self.text(c,'长剑 +2 · 力量差 1',(123,604),33,MUTED,ease((t-.65)/.6))
            p=pose((2040,180,1.0),(1110,158,1.04),t/.55)
            self.ui(c,frame,p); self.pointer(c,t,2.0,(p[0]+495*p[2],p[1]+238*p[2]))
        elif name == 'reason':
            p=pose((1110,158,1.04),(340,-200,2.2),t/.4)
            self.ui(c,frame,p,viewport=(118,145,1800,915))
            self.text(c,'需求 15 · 当前 14',(118,955),31,WHITE,ease(t/.35),True)
        elif name == 'open':
            self.words(c,['花之前，','先试。'],t,y=282,size=94)
            self.text(c,'从装备资料直接进入计算',(123,600),31,MUTED,ease((t-.5)/.6))
            p=(1075,110,.76);self.ui(c,frame,p)
            self.pointer(c,t,1.46,(p[0]+139*p[2],p[1]+945*p[2]))
        elif name == 'edit':
            p=pose((1075,110,.76),(130,-240,2.35),t/.7)
            self.ui(c,frame,p,viewport=(118,195,1802,660))
            self.text(c,'手动试算',(120,137),27,MUTED)
            self.words(c,['假设再升一级。'],t-.2,x=118,y=766,size=73)
            self.pointer(c,t,1.46,(p[0]+130*p[2],p[1]+315*p[2]))
            self.text(c,'+2',(1490,752),112,MUTED,1-ease((t-1.5)/.35),True)
            self.text(c,'+3',(1490,752+45*(1-ease((t-1.5)/.4))),112,GOLD,ease((t-1.5)/.4),True)
        elif name == 'calculate':
            p=pose((460,-720,1.4),(460,-55,1.4),(t-1.13)/.7)
            viewport=pose((420,460,1500,810),(118,130,1802,915),(t-1.13)/.7)
            self.ui(c,frame,p,viewport=tuple(round(v) for v in viewport))
            self.pointer(c,t,1.02,(p[0]+108*p[2],p[1]+945*p[2]))
            self.text(c,'点击计算，看看变化。',(118,955),29,WHITE,1,True)
        elif name == 'result':
            p=pose((970,98,1.1),(970,-180,1.1),(t-1.45)/.9);self.ui(c,frame,p)
            self.pointer(c,t,1.28,(p[0]+663*p[2],p[1]+585*p[2]))
            self.words(c,['力量门槛'],t,y=268,size=64)
            n=ease((t-1.3)/.5)
            self.text(c,'15 →',(122,430),84,MUTED,1,True)
            self.text(c,'14',(435,390+35*(1-n)),138,GOLD,n,True)
            self.text(c,'长剑 +2 → +3',(125,570),34,WHITE)
            self.text(c,'示例条件，无其他特殊修正',(125,641),26,MUTED,ease((t-2.3)/.4))
            self.text(c,'算清楚，再决定。',(125,756),42,WHITE,ease((t-3.1)/.6),True)
        elif name == 'collapse':
            c=self.gameplay(game_context,t,.23)
            self.ui(c,frame,(1120,125,.72),viewport=(118,120,1802,915),crop=(0,0,62,118) if t>=39/FPS else None)
            self.pointer(c,t,1.27,(1120+45*.72,125+45*.72))
            self.words(c,['把画面，','留给游戏。'],t-1.35,x=118,y=580,size=67)
        elif name == 'expand':
            c=self.gameplay(game_context,t+3,.23)
            self.ui(c,frame,(1120,125,.72),viewport=(118,120,1802,915),crop=None if t>=31/FPS else (0,0,62,118))
            self.pointer(c,t,1.0,(1120+31*.72,125+60*.72))
            self.words(c,['需要时，','接着看。'],t-1.2,x=118,y=580,size=67)
        elif name == 'outro':
            c=self.gameplay(frame,t,.72);reveal=ease(t/.75)
            halo=Image.new('RGBA',SIZE);d=ImageDraw.Draw(halo);r=90+5*math.sin(t*2)
            d.ellipse((960-r,260-r,960+r,260+r),fill=(*GOLD,45))
            c.alpha_composite(halo.filter(ImageFilter.GaussianBlur(38)))
            c.alpha_composite(self.logo.resize((142,142),Image.Resampling.NEAREST),(889,round(189+45*(1-reveal))))
            self.centered(c,'灯火',394+40*(1-reveal),112,WHITE,reveal,True)
            self.centered(c,'把关键选择，看得更清楚。',590,56,WHITE,ease((t-.6)/.6),True)
            self.centered(c,'破碎的像素地牢 · Windows 随行助手',691,32,MUTED,ease((t-1)/.6))
            self.centered(c,'github.com/Legender134/denghuo',803,39,GOLD,ease((t-1.5)/.5))
            self.centered(c,'独立开源项目 · 非游戏官方产品',955,25,MUTED,ease((t-1.5)/.5))
        self.chrome(c,absolute,name)
        if name not in ('game','outro'):
            note='演示条件 · 镜头放大'
            self.text(c,note,(1800-self.font(28).getlength(note),955),28,MUTED)
        if name in ('problem','open','collapse','outro') and t<.25:
            x=int(-140+ease(t/.25)*2200);d=ImageDraw.Draw(c,'RGBA')
            d.polygon([(x-75,0),(x+6,0),(x-110,1080),(x-191,1080)],fill=(*GOLD,180))
        return c.convert('RGB')


def soundtrack(path):
    """Original stereo score: warm chords, bass, plucks and synchronized Foley."""
    rate=48000;length=int(DURATION*rate)
    audio=np.zeros((length,2),dtype=np.float32);rng=np.random.default_rng(1704)
    def add(start,signal,amplitude=1,pan=0):
        begin=int(start*rate);stop=min(length,begin+len(signal))
        if stop<=begin:return
        signal=signal[:stop-begin]*amplitude
        audio[begin:stop,0]+=signal*math.sqrt((1-pan)/2)
        audio[begin:stop,1]+=signal*math.sqrt((1+pan)/2)
    def tone(freq,seconds,attack=.01,decay=3,harmonic=.2):
        t=np.arange(int(seconds*rate))/rate
        env=(1-np.exp(-t/max(.001,attack)))*np.exp(-t*decay)*np.minimum(1,(seconds-t)/.06)
        return (np.sin(2*np.pi*freq*t)+harmonic*np.sin(4*np.pi*freq*t))*env
    roots=[110,87.307,130.813,97.999]
    for bar,start in enumerate(np.arange(0,DURATION,4)):
        root=roots[bar%4]
        for semitone in (0,3 if bar%4==0 else 4,7):
            add(start,tone(root*2*2**(semitone/12),4.5,.4,.4,.1),.045,(semitone-3)/10)
        for step in range(16):
            when=start+step*.25
            if when<3.5 or when>30 or step%8==7:continue
            third=3 if bar%4==0 else 4
            note=root*4*2**([0,7,12,7,third,7,12,7][step%8]/12)
            add(when,tone(note,.65,.006,8,.25),.055,(-1 if step%2 else 1)*.36)
        for beat in range(8):
            when=start+beat*.5
            if when>DURATION-3:continue
            add(when,tone(root,.42,.012,6,.2),.1)
            if beat%2==0:
                t=np.arange(int(.25*rate))/rate
                kick=np.sin(2*np.pi*(46*t+1.4*(1-np.exp(-t*35))))*np.exp(-t*22)
                add(when,kick,.2 if when>3 else .1)
            if 3.5<=when<30:
                noise=np.diff(rng.normal(0,1,int(.065*rate)),prepend=0)
                add(when,noise*np.exp(-np.arange(len(noise))/rate*75),.014,.3)
                if beat%4==2:
                    noise=rng.normal(0,1,int(.15*rate))
                    add(when,noise*np.exp(-np.arange(len(noise))/rate*29),.032,-.15)
    for at in (5.5,11.46,14.46,17.02,20.28,25.27,28.0):
        add(at,tone(1450,.085,.001,70,.1),.16,.15)
        add(at+.018,tone(780,.08,.001,55,.1),.08,-.15)
    for at in (3.5,10,24,30):
        n=int(.27*rate);t=np.arange(n)/rate
        noise=np.convolve(rng.normal(0,1,n),np.ones(10)/10,'same')
        add(max(0,at-.13),noise*np.sin(np.pi*t/.27)**2,.12,-.25)
    fade=np.minimum(1,np.arange(length)/rate/.35)*np.minimum(1,(length-np.arange(length))/rate/1.8)
    audio*=fade[:,None];peak=float(np.max(np.abs(audio)))
    if peak>0:audio*=.82/peak
    with wave.open(str(path),'wb') as output:
        output.setparams((2,2,rate,0,'NONE','not compressed'))
        output.writeframes((audio*32767).astype('<i2').tobytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--footage',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/msyh.ttc'))
    parser.add_argument('--bold-font',type=Path,default=Path('C:/Windows/Fonts/msyhbd.ttc'))
    parser.add_argument('--ffmpeg',default='ffmpeg')
    args=parser.parse_args()
    if not args.font.is_file() or not args.bold_font.is_file():parser.error('Supply installed Chinese font files.')
    if not shutil.which(args.ffmpeg):parser.error('FFmpeg is required.')
    takes=load_footage(args.footage)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    film=Film(args.font,args.bold_font)
    audio=output/'original-score.wav';soundtrack(audio)
    video=output/'denghuo-introduction-0.7.0-motion.mp4'
    command=[args.ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080',
             '-r',str(FPS),'-i','-','-i',str(audio),'-c:v','libx264','-preset','fast','-crf','18',
             '-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
             '-af','loudnorm=I=-18:TP=-1.5:LRA=7','-ar','48000','-t',str(DURATION),'-movflags','+faststart',str(video)]
    encoder=subprocess.Popen(command,stdin=subprocess.PIPE)
    frames=[];start=0;context_reader=None
    try:
        for name,duration in SCENES:
            reader=Reader(args.ffmpeg,takes[name])
            if name=='collapse':context_reader=Reader(args.ffmpeg,takes['outro'])
            try:
                for index in range(round(duration*FPS)):
                    t=index/FPS
                    context=context_reader.frame() if name in ('collapse','expand') else None
                    frame=film.render(name,reader.frame(),t,start+t,context)
                    encoder.stdin.write(frame.tobytes())
                    if index in (round(duration*FPS*.3),round(duration*FPS*.8)):
                        path=output/f'{start+t:05.2f}-{name}.jpg';frame.save(path,quality=93);frames.append(path.name)
            finally:reader.close()
            if name=='expand':context_reader.close();context_reader=None
            start+=duration;print(f'Rendered {name}: {start:.1f}/{DURATION:.1f}s',flush=True)
    finally:
        if context_reader is not None:context_reader.close()
        encoder.stdin.close();result=encoder.wait()
    if result!=0:raise RuntimeError('Video encode failed.')
    receipt={'video':video.name,'duration_seconds':DURATION,'size':SIZE,'fps':FPS,
             'input_manifest_sha256':digest(args.footage),'renderer_sha256':digest(Path(__file__)),
             'logo_sha256':digest(ROOT/'data/lamp.png'),
             'font_sha256':digest(args.font),'bold_font_sha256':digest(args.bold_font),
             'inputs':{n:{k:v for k,v in i.items() if k!='path'} for n,i in takes.items()},
             'audio':'Original code-generated stereo score and synchronized click/whoosh sounds; no voiceover',
             'editing':'Trimmed real-time recordings, excluding four incomplete window-repaint frames. Editorial camera, captions and pointer; labeled gameplay composite at24-30s. No redrawn UI or changed values.',
             'frames':frames,'video_sha256':digest(video)}
    (output/'render.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'video':str(video),'sha256':receipt['video_sha256']},ensure_ascii=False))


if __name__=='__main__':main()
