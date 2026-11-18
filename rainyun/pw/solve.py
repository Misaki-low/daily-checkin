"""雨云腾讯「依次点选」验证码求解 v5
背景符号 → 连通域裁切 → 归一化 → 双向 Chamfer 距离 + 小角度旋转 → 最优指派
输出 JSON {"points":[[x,y]x3], "scores":[..]}，坐标为 iframe 内 CSS 像素
"""
import cv2
import numpy as np
import itertools
import json
import sys

SCALE = 2.0
SIZE = 64
ANGLES = range(-30, 31, 5)
MIN_DIST = 20


def imread_u(path):
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        if buf.size == 0:
            return None
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def ink_mask(img, thr=55):
    """符号是中性纯黑描边：亮度低 + 三通道接近；照片暗部（毛发等）饱和度偏高"""
    mx = np.max(img, axis=2).astype(np.int16)
    mn = np.min(img, axis=2).astype(np.int16)
    sat = mx - mn
    return (((mx < thr) & (sat < 22)) * 255).astype(np.uint8)


def split_hint(hint):
    m = ink_mask(hint)
    cols = (m > 0).sum(axis=0)
    groups, start, gap = [], None, 0
    for i, v in enumerate(cols):
        if v > 0:
            if start is None:
                start = i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= 5:
                    groups.append((start, i - gap))
                    start = None
                    gap = 0
    if start is not None:
        groups.append((start, len(cols) - 1))
    out = []
    for x1, x2 in groups:
        sub = m[:, x1:x2 + 1]
        rows = (sub > 0).sum(axis=1)
        ys = np.where(rows > 0)[0]
        if len(ys) == 0:
            continue
        t = sub[ys[0]:ys[-1] + 1, :]
        if t.shape[1] < 8 or t.shape[0] < 12:
            continue
        out.append(t)
    return out


def bg_symbols(bgmask):
    m = cv2.dilate(bgmask, np.ones((3, 3), np.uint8), iterations=1)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    H, W = bgmask.shape
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if w < 26 or h < 26 or w > min(W * 0.7, 190) or h > min(H * 0.7, 190):
            continue
        if a < 180:
            continue
        fill = a / float(w * h)
        if fill > 0.6:
            continue
        sub = np.where(lab[y:y + h, x:x + w] == i, bgmask[y:y + h, x:x + w], 0)
        if (sub > 0).sum() < 150:
            continue
        out.append((x + w / 2.0, y + h / 2.0, sub))
    return out


def norm(mask):
    h, w = mask.shape
    pad = 6
    s = (SIZE - 2 * pad) / float(max(w, h))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    rs = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((SIZE, SIZE), np.uint8)
    oy, ox = (SIZE - nh) // 2, (SIZE - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = (rs > 60).astype(np.uint8)
    return canvas


def chamfer(a, b, cap=18.0):
    if a.sum() == 0 or b.sum() == 0:
        return cap
    Da = cv2.distanceTransform((1 - a).astype(np.uint8), cv2.DIST_L2, 5)
    Db = cv2.distanceTransform((1 - b).astype(np.uint8), cv2.DIST_L2, 5)
    fwd = float(Da[b > 0].mean())
    bwd = float(Db[a > 0].mean())
    return min((fwd + bwd) / 2.0, cap)


def best_match(tmpl, cands):
    out = []
    for cx, cy, sub in cands:
        c = norm(sub)
        best = 1e9
        for ang in ANGLES:
            M = cv2.getRotationMatrix2D((SIZE / 2.0, SIZE / 2.0), ang, 1.0)
            rot = cv2.warpAffine(tmpl, M, (SIZE, SIZE), flags=cv2.INTER_NEAREST, borderValue=0)
            d = chamfer(c, rot)
            if d < best:
                best = d
        out.append((1.0 - best / 18.0, cx, cy))
    out.sort(key=lambda t: -t[0])
    return out


def main():
    bg_path = sys.argv[1] if len(sys.argv) > 1 else "cap_bg.png"
    hint_path = sys.argv[2] if len(sys.argv) > 2 else "cap_hint.png"
    vis = '--vis' in sys.argv
    bg = imread_u(bg_path)
    hint = imread_u(hint_path)
    if bg is None or hint is None:
        print(json.dumps({"error": "image_not_found"}))
        return 1
    glyphs = split_hint(hint)
    if len(glyphs) != 3:
        print(json.dumps({"error": "hint_glyph_count=%d" % len(glyphs)}))
        return 1
    tmpls = [norm(g) for g in glyphs]
    symbols = bg_symbols(ink_mask(bg))
    if len(symbols) < 3:
        print(json.dumps({"error": "symbols=%d" % len(symbols)}))
        return 1

    cands = [best_match(t, symbols)[:4] for t in tmpls]
    best = None
    for combo in itertools.product(*[range(len(c)) for c in cands]):
        pts = [cands[i][j] for i, j in enumerate(combo)]
        ok = True
        for a, b in itertools.combinations(pts, 2):
            if (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2 < MIN_DIST ** 2:
                ok = False
                break
        if not ok:
            continue
        score = sum(p[0] for p in pts)
        if best is None or score > best[0]:
            best = (score, pts)
    if best is None:
        print(json.dumps({"error": "no_valid_assignment"}))
        return 1
    pts = best[1]

    if vis:
        img = bg.copy()
        for i, (s, x, y) in enumerate(pts):
            cv2.circle(img, (int(x), int(y)), 26, (0, 0, 255), 3)
            cv2.putText(img, str(i + 1), (int(x) - 8, int(y) + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
        for x, y, _ in symbols:
            cv2.rectangle(img, (int(x) - 3, int(y) - 3), (int(x) + 3, int(y) + 3), (0, 255, 0), 1)
        out_png = bg_path.replace('.png', '_vis.png')
        cv2.imencode('.png', img)[1].tofile(out_png)
        print('VIS', out_png)

    print(json.dumps({
        "points": [[round(p[1] / SCALE), round(p[2] / SCALE)] for p in pts],
        "scores": [round(p[0], 3) for p in pts],
        "total": round(best[0], 3),
        "n_symbols": len(symbols),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
