"""Generates the animated gold line-art backdrop used by the login and Ask screens:
  static/skyline.svg  - wireframe city towers along the bottom
  static/waves.svg    - flowing ribbons of fine gold lines + stars
Run:  python scripts/make_backdrop.py   (output is deterministic)
"""
import math
import os
import random

OUT = os.path.join(os.path.dirname(__file__), "..", "static")
GOLD, GOLD_LIGHT, NAVY = "#C9A961", "#F3E2B0", "#0B1F45"


def f(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ skyline
def building(x, g, w, h, d, op, rnd, tall=False):
    """Wireframe tower: front face, side face and roof, with floor lines and mullions."""
    k = 0.42  # perspective slope of the side face
    top = g - h
    out = []
    side = f"M{f(x+w)},{f(top)} L{f(x+w+d)},{f(top-d*k)} L{f(x+w+d)},{f(g-d*k)} L{f(x+w)},{f(g)} Z"
    roof = f"M{f(x)},{f(top)} L{f(x+d)},{f(top-d*k)} L{f(x+w+d)},{f(top-d*k)} L{f(x+w)},{f(top)} Z"
    out.append(f'<path d="{side}" fill="#0a1c40" fill-opacity=".72" stroke="{GOLD}" stroke-opacity="{min(1, op*1.15):.2f}"/>')
    out.append(f'<path d="{roof}" fill="#0d2552" fill-opacity=".8" stroke="{GOLD}" stroke-opacity="{min(1, op*1.4):.2f}"/>')
    out.append(f'<rect x="{f(x)}" y="{f(top)}" width="{f(w)}" height="{f(h)}" fill="#0c2150" fill-opacity=".62" stroke="{GOLD}" stroke-opacity="{min(1, op*1.4):.2f}"/>')
    det = []
    fs = rnd.choice([10, 12, 14, 16])
    y = top + fs
    while y < g - 2:
        det.append(f"M{f(x)},{f(y)}h{f(w)}")
        det.append(f"M{f(x+w)},{f(y)}l{f(d)},{f(-d*k)}")
        y += fs
    cols = max(3, int(w / rnd.choice([10, 13, 16, 20])))
    for i in range(1, cols):
        det.append(f"M{f(x + w * i / cols)},{f(top)}V{f(g)}")
    for i in range(1, 3):
        xx = x + w + d * i / 3
        det.append(f"M{f(xx)},{f(top - d*k*i/3)}V{f(g - d*k*i/3)}")
    out.append(f'<path d="{"".join(det)}" stroke="{GOLD}" stroke-opacity="{op*.62:.2f}" stroke-width=".55"/>')
    if tall:  # crown + spire
        cx = x + w / 2
        out.append(f'<path d="M{f(x+6)},{f(top)} L{f(cx)},{f(top-26)} L{f(x+w-6)},{f(top)} M{f(cx)},{f(top-26)}V{f(top-70)}" '
                   f'stroke="{GOLD}" stroke-opacity="{op:.2f}"/>')
    # a few lit windows, some of which twinkle
    for _ in range(int(w * h / 4000)):
        lx = x + rnd.random() * (w - 5)
        ly = top + 6 + rnd.random() * (h - 14)
        cls = ' class="tw"' if rnd.random() < .35 else ""
        out.append(f'<rect{cls} x="{f(lx)}" y="{f(ly)}" width="3" height="2" fill="{GOLD_LIGHT}" opacity="{rnd.uniform(.35, .85):.2f}"/>')
    return "\n".join(out)


def skyline():
    rnd = random.Random(7)
    W, H, g = 2400, 780, 720
    back, front = [], []
    # back row: taller, fainter, with the landmark tower in the middle
    x = -40
    while x < W:
        w = rnd.randint(70, 150)
        near = max(0.0, 1 - abs(x + w / 2 - W / 2) / 900)
        h = rnd.randint(160, 300) + int(near * 220)
        back.append(building(x, g - 30, w, h, rnd.randint(18, 34), .42, rnd))
        x += w + rnd.randint(10, 60)
    landmark = building(W / 2 - 55, g - 10, 110, 600, 40, .8, rnd, tall=True)
    # front row: lower, brighter
    x = -30
    while x < W:
        w = rnd.randint(60, 170)
        if abs(x + w / 2 - W / 2) < 120:  # keep the landmark visible
            x += 150
            continue
        h = rnd.randint(70, 230)
        front.append(building(x, g + 10, w, h, rnd.randint(14, 30), .72, rnd))
        x += w + rnd.randint(30, 140)
    # sweeping road / light-trail lines along the ground
    roads = []
    for i in range(7):
        y0 = g + 6 + i * 7
        roads.append(f'<path d="M-50,{y0+40} C 500,{y0-30-i*4} 1100,{y0+30} 1500,{y0-10} S 2200,{y0-60+i*3} 2500,{y0-20}" '
                     f'stroke="{GOLD}" stroke-opacity="{.18+.06*(i%3):.2f}" stroke-width=".8" fill="none"/>')
    trail = (f'<path class="run" d="M-50,{g+44} C 500,{g-28} 1100,{g+36} 1500,{g-4} S 2200,{g-54} 2500,{g-14}" '
             f'stroke="{GOLD_LIGHT}" stroke-width="1.6" fill="none" stroke-linecap="round"/>')
    fade = (f'<defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NAVY}" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="{NAVY}" stop-opacity=".9"/></linearGradient>'
            f'<radialGradient id="glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{GOLD_LIGHT}" stop-opacity=".9"/>'
            f'<stop offset="1" stop-color="{GOLD}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="hz" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{GOLD}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{GOLD}" stop-opacity="0"/></radialGradient></defs>')
    glows = "".join(f'<circle class="tw" cx="{f(cx)}" cy="{f(cy)}" r="{r}" fill="url(#glow)"/>'
                    for cx, cy, r in [(W/2-58, g-160, 10), (W/2+70, g-340, 7), (760, g-60, 9), (1640, g-90, 8), (420, g-20, 7)])
    style = ("<style>.run{stroke-dasharray:180 3200;animation:run 11s linear infinite}"
             "@keyframes run{from{stroke-dashoffset:3380}to{stroke-dashoffset:0}}"
             ".tw{animation:tw 3.2s ease-in-out infinite alternate}.tw:nth-of-type(3n){animation-duration:4.6s}"
             ".tw:nth-of-type(4n){animation-delay:-2s}@keyframes tw{from{opacity:.15}to{opacity:.95}}"
             "@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMax slice" fill="none" '
           f'stroke-width="1" shape-rendering="geometricPrecision">{style}{fade}'
           f'<ellipse cx="{W/2}" cy="{g}" rx="{W*.55}" ry="170" fill="url(#hz)"/>'
           f'<g>{"".join(back)}</g><g>{landmark}</g><g>{"".join(front)}</g>{"".join(roads)}{trail}{glows}'
           f'<rect x="0" y="{g+20}" width="{W}" height="{H-g-20}" fill="url(#fade)"/></svg>')
    return svg


# ------------------------------------------------------------------ waves + stars
def ribbon(n, p0, c1, c2, p1, spread, twist, op_min, op_max, rnd):
    lines = []
    for i in range(n):
        t = i / (n - 1)
        s = math.sin(t * math.pi)  # lines bunch together at the ends, spread in the middle
        dy1 = (t - .5) * spread * 2 * (1 + twist)
        dy2 = -(t - .5) * spread * 1.4 * (1 - twist)
        e = (t - .5) * spread * .35
        d = (f"M{f(p0[0])},{f(p0[1] + e)} C{f(c1[0])},{f(c1[1] + dy1)} {f(c2[0])},{f(c2[1] + dy2)} "
             f"{f(p1[0])},{f(p1[1] + e * 1.6)}")
        op = op_min + (op_max - op_min) * (.35 + .65 * s) * rnd.uniform(.7, 1)
        lines.append(f'<path d="{d}" stroke-opacity="{op:.2f}"/>')
    return "".join(lines)


def waves():
    rnd = random.Random(11)
    W, H = 1600, 1000
    a = ribbon(34, (-120, 700), (360, 480), (950, 840), (1760, 390), 240, .3, .14, .78, rnd)
    d = ribbon(24, (500, 1060), (950, 740), (1300, 920), (1760, 630), 170, -.2, .1, .6, rnd)
    b = ribbon(24, (700, -60), (1080, 170), (1320, 10), (1760, 240), 150, -.3, .08, .55, rnd)
    c = ribbon(16, (-120, 320), (300, 240), (700, 410), (1100, 230), 80, .1, .05, .26, rnd)
    hl1 = ('<path class="run" d="M-120,690 C380,520 900,760 1760,430" stroke="#F3E2B0" stroke-width="1.5" stroke-linecap="round"/>')
    hl2 = ('<path class="run r2" d="M760,-60 C1100,120 1300,40 1760,210" stroke="#F3E2B0" stroke-width="1.2" stroke-linecap="round"/>')
    stars = []
    for i in range(150):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H * .82)
        r = rnd.choice([.6, .7, .8, 1, 1.2, 1.6])
        cls = ' class="tw"' if i % 5 == 0 else ""
        stars.append(f'<circle{cls} cx="{f(x)}" cy="{f(y)}" r="{r}" fill="#F6E7BE" opacity="{rnd.uniform(.15, .7):.2f}"/>')
    style = ("<style>.sway{animation:sway 16s ease-in-out infinite alternate;transform-box:fill-box}"
             ".sway2{animation:sway 21s ease-in-out -6s infinite alternate-reverse}"
             "@keyframes sway{to{transform:translate(-28px,16px)}}"
             ".run{stroke-dasharray:110 2300;animation:run 9s linear infinite}.r2{animation-duration:13s;animation-delay:-5s}"
             "@keyframes run{from{stroke-dashoffset:2410}to{stroke-dashoffset:0}}"
             ".tw{animation:tw 2.8s ease-in-out infinite alternate}.tw:nth-of-type(2n){animation-duration:4.1s;animation-delay:-1.3s}"
             "@keyframes tw{from{opacity:.1}to{opacity:.9}}@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" fill="none">'
            f'{style}<g>{"".join(stars)}</g>'
            f'<g class="sway" stroke="{GOLD}" stroke-width=".6">{a}{hl1}</g>'
            f'<g class="sway2" stroke="{GOLD}" stroke-width=".6">{d}</g>'
            f'<g class="sway2" stroke="{GOLD}" stroke-width=".6">{b}{hl2}</g>'
            f'<g stroke="{GOLD}" stroke-width=".5">{c}</g></svg>')


if __name__ == "__main__":
    for name, svg in (("skyline.svg", skyline()), ("waves.svg", waves())):
        path = os.path.join(OUT, name)
        with open(path, "w") as fh:
            fh.write(svg)
        print(f"{name}: {len(svg)/1024:.0f} KB")
