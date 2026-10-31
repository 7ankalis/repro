"""
Grouped-bar chart for the video / README: Repro vs LLM judge (task C5).

    python scripts/make_eval_chart.py                                   # runs/eval_comparison.json -> runs/eval_chart.png
    python scripts/make_eval_chart.py tests/eval_comparison_sample.json -o runs/eval_chart_sample.png

Input is the eval_comparison.json written by `repro eval` (repro/eval.py::write_comparison):
    {"methods": {"repro": {...}, "llm_judge": {...}}, "same_reports": true}

Groups (all as % so they share ONE axis): real bugs confirmed, slop rejected, false VERIFIED on slop.
Cost has a different scale, so it is printed under the chart instead of plotted on a second axis.

Pure stdlib (zlib + a 5x7 bitmap font): no plotting dependency to install.
"""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

# ----------------------------------------------------------------------------- palette (light surface)
SURFACE = (0xFC, 0xFC, 0xFB)
TEXT = (0x0B, 0x0B, 0x0B)
TEXT_2 = (0x52, 0x51, 0x4E)
GRID = (0xE4, 0xE3, 0xDF)
AXIS = (0xB5, 0xB4, 0xAE)
SERIES = {"repro": (0x2A, 0x78, 0xD6), "llm_judge": (0xEB, 0x68, 0x34)}   # categorical slots 1, 2
LABELS = {"repro": "REPRO", "llm_judge": "LLM JUDGE"}

# ----------------------------------------------------------------------------- 5x7 font
_F = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
    ",": "00000 00000 00000 00000 01100 00100 01000", ":": "00000 01100 01100 00000 01100 01100 00000",
    "%": "11000 11001 00010 00100 01000 10011 00011", "$": "00100 01111 10100 01110 00101 11110 00100",
    "/": "00000 00001 00010 00100 01000 10000 00000", "-": "00000 00000 00000 11111 00000 00000 00000",
    "(": "00010 00100 01000 01000 01000 00100 00010", ")": "01000 00100 00010 00010 00010 00100 01000",
    "+": "00000 00100 00100 11111 00100 00100 00000", "=": "00000 00000 11111 00000 11111 00000 00000",
    "'": "00100 00100 01000 00000 00000 00000 00000", "?": "01110 10001 00001 00010 00100 00000 00100",
    "!": "00100 00100 00100 00100 00100 00000 00100", "<": "00010 00100 01000 10000 01000 00100 00010",
    ">": "01000 00100 00010 00001 00010 00100 01000", "|": "00100 00100 00100 00100 00100 00100 00100",
}
FONT = {c: [row for row in g.split()] for c, g in _F.items()}


class Canvas:
    def __init__(self, w: int, h: int, bg=SURFACE) -> None:
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def rect(self, x0: int, y0: int, x1: int, y1: int, color, round_top: int = 0) -> None:
        x0, x1 = max(0, min(x0, x1)), min(self.w, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(self.h, max(y0, y1))
        c = bytes(color)
        for y in range(y0, y1):
            inset = 0
            dy = y - y0
            if round_top and dy < round_top:     # quarter-circle corners on the data end
                r = round_top
                inset = r - int((r * r - (r - dy - 0.5) ** 2) ** 0.5 + 0.5)
            a, b = x0 + inset, x1 - inset
            if b > a:
                i = (y * self.w + a) * 3
                self.px[i:i + (b - a) * 3] = c * (b - a)

    def text(self, x: int, y: int, s: str, color=TEXT, scale: int = 2, anchor: str = "left") -> int:
        s = s.upper()
        width = text_width(s, scale)
        if anchor == "center":
            x -= width // 2
        elif anchor == "right":
            x -= width
        cx = x
        for ch in s:
            g = FONT.get(ch, FONT["?"])
            for ry, row in enumerate(g):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        self.rect(cx + rx * scale, y + ry * scale, cx + (rx + 1) * scale, y + (ry + 1) * scale, color)
            cx += 6 * scale
        return width

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def text_width(s: str, scale: int) -> int:
    return max(0, len(s) * 6 * scale - scale)


# ----------------------------------------------------------------------------- data
GROUPS = [  # (count key, denominator key, pct key, label lines, note)
    ("real_confirmed", "n_real", "real_confirmed_pct", ["REAL BUGS", "CONFIRMED"], "HIGHER IS BETTER"),
    ("slop_rejected", "n_slop", "slop_rejected_pct", ["SLOP", "REJECTED"], "HIGHER IS BETTER"),
    ("false_verified_on_slop", "n_slop", None, ["SLOP CALLED", "VALID/VERIFIED"], "LOWER IS BETTER"),
]


def chart_values(methods: dict[str, dict]) -> list[list[tuple[float | None, str, str]]]:
    """[group][method] -> (percent or None, percent label, count label)."""
    out = []
    for count_k, den_k, pct_k, _, _ in GROUPS:
        row = []
        for m in methods.values():
            n, den = m.get(count_k), m.get(den_k)
            if n is None or not den:
                row.append((None, "N/A", ""))
                continue
            pct = m.get(pct_k) if pct_k and m.get(pct_k) is not None else round(100 * n / den, 1)
            row.append((float(pct), f"{pct:g}%", f"{n}/{den}"))
        out.append(row)
    return out


def _money(v) -> str:
    return "N/A" if v is None else f"${v:.4f}" if v < 0.1 else f"${v:.2f}"


def render_chart(comp: dict, w: int = 1280, h: int = 720) -> bytes:
    methods = {k: v for k, v in comp["methods"].items() if k in SERIES}
    if not methods:
        raise ValueError("no known methods in comparison JSON")
    c = Canvas(w, h)
    left, right, top, bottom = 110, w - 60, 170, h - 190

    c.text(60, 36, "REPRO VS LLM JUDGE ON THE SAME REPORTS", TEXT, scale=4)
    n_real = next(iter(methods.values())).get("n_real")
    n_slop = next(iter(methods.values())).get("n_slop")
    c.text(60, 84, f"{n_real} REAL + {n_slop} SLOP REPORTS - BARS ARE % OF EACH SET", TEXT_2, scale=2)

    # legend (top right)
    lx = right
    for key in reversed(list(methods)):
        label = LABELS[key]
        lx -= text_width(label, 2)
        c.text(lx, 88, label, TEXT, scale=2)
        lx -= 26
        c.rect(lx, 86, lx + 18, 104, SERIES[key], round_top=3)
        lx -= 30

    # grid + y axis labels (0..100%)
    plot_h = bottom - top
    for t in range(0, 101, 25):
        y = bottom - round(plot_h * t / 100)
        c.rect(left, y - 1, right, y + 1, AXIS if t == 0 else GRID)
        c.text(left - 14, y - 7, f"{t}%", TEXT_2, scale=2, anchor="right")

    values = chart_values(methods)
    group_w = (right - left) / len(GROUPS)
    bar_w, gap = 110, 8
    nm = len(methods)
    for gi, (group, (_, _, _, lines, note)) in enumerate(zip(values, GROUPS, strict=True)):
        cx = left + group_w * (gi + 0.5)
        x = round(cx - (nm * bar_w + (nm - 1) * gap) / 2)
        for key, (pct, label, count) in zip(methods, group, strict=True):
            if pct is not None:
                bh = max(3, round(plot_h * pct / 100))     # a 0 still shows as a stub on the baseline
                c.rect(x, bottom - bh, x + bar_w, bottom - 1, SERIES[key], round_top=4 if bh > 8 else 0)
                vy = bottom - bh - 50
            else:
                vy = bottom - 50
            c.text(x + bar_w // 2, vy, label, TEXT, scale=2, anchor="center")
            c.text(x + bar_w // 2, vy + 24, count, TEXT_2, scale=2, anchor="center")
            x += bar_w + gap
        for li, line in enumerate(lines):
            c.text(round(cx), bottom + 20 + li * 24, line, TEXT, scale=2, anchor="center")
        c.text(round(cx), bottom + 20 + len(lines) * 24 + 4, note, TEXT_2, scale=2, anchor="center")

    # cost line (different scale -> text, not a second axis)
    parts = [f"{LABELS[k]} {_money(m.get('median_cost_usd'))}/REPORT ({_money(m.get('total_cost_usd'))} TOTAL)"
             for k, m in methods.items()]
    c.text(60, h - 64, "COST: " + "   |   ".join(parts), TEXT_2, scale=2)
    if not comp.get("same_reports", True):
        c.text(60, h - 34, "WARNING: METHODS WERE RUN ON DIFFERENT REPORT SETS", SERIES["llm_judge"], scale=2)
    return c.png()


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("comparison", nargs="?", type=Path, default=Path("runs/eval_comparison.json"))
    ap.add_argument("-o", "--out", type=Path, default=Path("runs/eval_chart.png"))
    a = ap.parse_args(argv)
    comp = json.loads(a.comparison.read_text())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(render_chart(comp))
    print(f"wrote {a.out}")
    return a.out


if __name__ == "__main__":
    main()
