"""Animate the L2 (MetalLB ARP mode) failover scene on top of the pixel-texture background."""
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import os, subprocess

BASE = Image.open('background.png').convert('RGB')  # 240x135
S = 5                                             # upscale factor -> 1200x675
FPS = 12
OUT = 'frames'
os.makedirs(OUT, exist_ok=True)

# geometry in 240x135 space
ROUTER = (120, 22)
CABLE = {
    'L': [(103, 26), (93, 26), (60, 63)],
    'M': [(119, 31), (119, 64)],
    'R': [(137, 26), (146, 26), (180, 63)],
}
RACK = {'L': (39, 64, 70, 128), 'M': (106, 64, 136, 128), 'R': (170, 64, 201, 128)}
FLOOR_Y = 126
GREEN, YELLOW, RED, WHITE = (120, 255, 120), (255, 230, 90), (255, 70, 70), (255, 255, 255)


def lerp_path(path, t):
    """Point at fraction t (0..1) along a polyline."""
    segs = list(zip(path, path[1:]))
    lens = [((b[0]-a[0])**2 + (b[1]-a[1])**2) ** .5 for a, b in segs]
    d = t * sum(lens)
    for (a, b), L in zip(segs, lens):
        if d <= L:
            k = d / L if L else 0
            return (a[0] + (b[0]-a[0]) * k, a[1] + (b[1]-a[1]) * k)
        d -= L
    return path[-1]


def packet(dr, xy, color, size=2):
    x, y = int(xy[0]), int(xy[1])
    dr.rectangle((x - size // 2, y - size // 2, x + size // 2, y + size // 2), fill=color)


def font(sz):
    try:
        return ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', sz, index=1)
    except Exception:
        return ImageFont.load_default()


def label(dr, xy, text, sz, fg, bg=(12, 14, 40)):
    f = font(sz)
    b = dr.textbbox(xy, text, font=f, anchor='mm')
    dr.rectangle((b[0]-10, b[1]-7, b[2]+10, b[3]+7), fill=bg, outline=fg, width=3)
    dr.text(xy, text, font=f, fill=fg, anchor='mm')


def tint(img, box, rgb, k):
    """Blend a rack area towards a colour (k 0..1)."""
    reg = img.crop(box)
    over = Image.new('RGB', reg.size, rgb)
    img.paste(Image.blend(reg, over, k), box)


def darken(img, box, k):
    reg = img.crop(box)
    img.paste(ImageEnhance.Brightness(ImageEnhance.Color(reg).enhance(0.2)).enhance(k), box)


PHASES = [  # (frames, name)
    (48, 'serve'),     # node-2 owns VIP, traffic flows
    (14, 'fail'),      # node-2 goes down
    (14, 'garp'),      # node-3 sends gratuitous ARP
    (48, 'moved'),     # traffic now goes to node-3
]
CAPTION = {
    'serve': ('node-2 owns the VIP and answers ARP', GREEN),
    'fail': ('node-2 goes down', RED),
    'garp': ('node-3 elected -> sends gratuitous ARP', YELLOW),
    'moved': ('VIP moved: traffic now lands on node-3', GREEN),
}

n = 0
for frames, ph in PHASES:
    for i in range(frames):
        im = BASE.copy()
        dr = ImageDraw.Draw(im)
        owner = 'M' if ph in ('serve', 'fail') else 'R'
        if ph != 'serve':
            darken(im, RACK['M'], 0.45 if ph == 'fail' and i % 4 < 2 else 0.35)
        if owner == 'R':
            tint(im, RACK['R'], (60, 200, 80), 0.35 + 0.1 * ((i // 3) % 2))
        dr = ImageDraw.Draw(im)
        if ph in ('serve', 'moved'):
            # client traffic: router -> owner rack
            for k in range(3):
                t = ((i / 16.0) + k / 3.0) % 1.0
                packet(dr, lerp_path(CABLE[owner], t), YELLOW)
            # kube-proxy spreads to pods on the other racks (along the floor)
            src_x = (RACK[owner][0] + RACK[owner][2]) // 2
            for other in [r for r in 'LMR' if r != owner and not (ph == 'moved' and r == 'M')]:
                dst_x = (RACK[other][0] + RACK[other][2]) // 2
                t = ((i / 20.0) + (0.5 if other == 'L' else 0)) % 1.0
                packet(dr, (src_x + (dst_x - src_x) * t, FLOOR_Y + 3), WHITE, 1)
        if ph == 'garp':
            t = i / (frames - 1)
            packet(dr, lerp_path(list(reversed(CABLE['R'])), t), GREEN, 3)
        big = im.resize((240 * S, 135 * S), Image.NEAREST)
        D = ImageDraw.Draw(big)
        label(D, (600, 30), 'KUBERNETES L2 LOAD BALANCING  (MetalLB, ARP mode)', 26, YELLOW)
        vx = (RACK[owner][0] + RACK[owner][2]) // 2 * S
        if not (ph == 'fail' and i % 4 >= 2):
            label(D, (vx, 290), 'VIP 192.168.1.240', 20, GREEN, (8, 40, 20))
        for r, name in zip('LMR', ('node-1', 'node-2', 'node-3')):
            cx = (RACK[r][0] + RACK[r][2]) // 2 * S
            col = RED if (r == 'M' and ph != 'serve') else WHITE
            label(D, (cx, 660 - 0), name if not (r == 'M' and ph != 'serve') else 'node-2  DOWN', 18, col)
        txt, col = CAPTION[ph]
        label(D, (600, 600), txt, 22, col)
        big.save(f'{OUT}/f{n:04d}.png')
        n += 1

print('frames', n)
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', f'{OUT}/f%04d.png',
                '-vf', 'pad=1200:676:0:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart',
                'l2_failover.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', f'{OUT}/f%04d.png',
                '-vf', 'split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=none',
                '-loop', '0', 'l2_failover.gif'], check=True)
Image.open(f'{OUT}/f0010.png').save('preview_serve.png')
Image.open(f'{OUT}/f0090.png').save('preview_moved.png')
print('ok')
