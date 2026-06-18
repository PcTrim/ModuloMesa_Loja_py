from collections import deque

from PIL import Image, ImageOps

src = r"c:\Users\joaqu\OneDrive\LojaOnline\static\img\pctrimLogo.jpg"
out = r"c:\Users\joaqu\OneDrive\LojaOnline\img\logo.ico"


def avg_corner_color(img, block=18):
    w, h = img.size
    points = []
    regions = [
        (0, 0, block, block),
        (w - block, 0, w, block),
        (0, h - block, block, h),
        (w - block, h - block, w, h),
    ]
    px = img.load()
    for x0, y0, x1, y1 in regions:
        for y in range(y0, y1):
            for x in range(x0, x1):
                points.append(px[x, y])
    r = sum(p[0] for p in points) // len(points)
    g = sum(p[1] for p in points) // len(points)
    b = sum(p[2] for p in points) // len(points)
    return r, g, b


def color_dist_sq(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


with Image.open(src).convert("RGB") as rgb:
    w, h = rgb.size
    target = avg_corner_color(rgb)
    tol = 56
    tol_sq = tol * tol

    px = rgb.load()
    candidate = [[False] * w for _ in range(h)]

    for y in range(h):
        for x in range(w):
            candidate[y][x] = color_dist_sq(px[x, y], target) <= tol_sq

    remove = [[False] * w for _ in range(h)]
    q = deque()

    for x in range(w):
        if candidate[0][x]:
            q.append((x, 0))
        if candidate[h - 1][x]:
            q.append((x, h - 1))
    for y in range(h):
        if candidate[y][0]:
            q.append((0, y))
        if candidate[y][w - 1]:
            q.append((w - 1, y))

    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        if remove[y][x] or not candidate[y][x]:
            continue
        remove[y][x] = True
        q.append((x + 1, y))
        q.append((x - 1, y))
        q.append((x, y + 1))
        q.append((x, y - 1))

    rgba = rgb.convert("RGBA")
    out_px = rgba.load()
    for y in range(h):
        for x in range(w):
            if remove[y][x]:
                out_px[x, y] = (out_px[x, y][0], out_px[x, y][1], out_px[x, y][2], 0)

    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)

    icon_base = ImageOps.pad(
        rgba,
        (512, 512),
        method=Image.Resampling.LANCZOS,
        color=(255, 255, 255, 0),
    )
    icon_base.save(
        out,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

print(out)
