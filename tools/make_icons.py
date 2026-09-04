"""
make_icons.py — the extension's icon, at the four sizes Chrome asks for.

Written by hand rather than with Pillow because the alternative is a build
dependency for four small squares. A PNG is a signature, a header, a zlib
stream of filtered scanlines and a checksum; that is about forty lines, and it
is forty lines that will still run on a machine with nothing installed.

The mark is a lane: three tracks converging on one. Two of them stop short and
the third carries through, which is the product in a shape — many models, one
chosen. It reads at 16px, which is the only size that really matters, because
that is the toolbar.
"""

from __future__ import annotations

import pathlib
import struct
import zlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "extension" / "icons"

# The one accent from ui.js, and white to draw on it.
BG = (0x34, 0x55, 0xF0)
FG = (0xFF, 0xFF, 0xFF)


def png(width: int, height: int, pixels: list[list[tuple]]) -> bytes:
    """Encode RGBA pixels as a PNG."""
    raw = bytearray()
    for row in pixels:
        raw.append(0)                      # filter type 0: none
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def blend(under: tuple, over: tuple, alpha: float) -> tuple:
    return tuple(round(u + (o - u) * alpha) for u, U in ((0, 0),) for u, o in
                 zip(under, over)) if False else tuple(
        round(u + (o - u) * alpha) for u, o in zip(under, over))


def draw(size: int) -> list[list[tuple]]:
    """Three tracks converging on one, on a rounded square.

    Supersampled four times in each direction: at 16px the difference between
    an anti-aliased edge and a stepped one is the difference between a mark and
    a mistake.
    """
    ss = 4
    n = size * ss
    radius = n * 0.24
    # Track geometry, in units of the full width.
    x0, x1 = 0.20 * n, 0.80 * n
    mid = 0.50 * n
    thick = max(1.0, n * 0.075)
    stop = 0.56 * n                        # where the outer tracks give up
    offset = n * 0.19                      # their distance from the centre

    def inside_square(x: float, y: float) -> bool:
        # Rounded rectangle: outside the corner circles is outside the shape.
        for cx, cy in ((radius, radius), (n - radius, radius),
                       (radius, n - radius), (n - radius, n - radius)):
            if ((x < radius or x > n - radius) and
                    (y < radius or y > n - radius)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                    return True
        if (x < radius or x > n - radius) and (y < radius or y > n - radius):
            return False
        return 0 <= x <= n and 0 <= y <= n

    def on_track(x: float, y: float) -> bool:
        if x < x0 or x > x1:
            return False
        # The centre track runs the whole way.
        if abs(y - mid) <= thick / 2:
            return True
        # The outer two run in, then stop — they bend toward the middle and
        # end, which is what makes this a convergence rather than a fork.
        for sign in (-1, 1):
            if x > stop:
                continue
            # Ease the outer track toward the centre as it approaches `stop`.
            t = max(0.0, min(1.0, (x - x0) / (stop - x0)))
            y_track = mid + sign * offset * (1 - t * t)
            if abs(y - y_track) <= thick / 2:
                return True
        return False

    out = []
    for py in range(size):
        row = []
        for px in range(size):
            hits_bg = 0
            hits_fg = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = px * ss + sx + 0.5
                    y = py * ss + sy + 0.5
                    if not inside_square(x, y):
                        continue
                    hits_bg += 1
                    if on_track(x, y):
                        hits_fg += 1
            total = ss * ss
            if not hits_bg:
                row.append((0, 0, 0, 0))
                continue
            alpha = hits_bg / total
            colour = blend(BG, FG, hits_fg / hits_bg) if hits_bg else BG
            row.append((colour[0], colour[1], colour[2], round(alpha * 255)))
        out.append(row)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        path = OUT / f"icon{size}.png"
        path.write_bytes(png(size, size, draw(size)))
        print(f"  {path.name}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
