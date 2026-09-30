"""Build the Q-GreenFleet logo files in docs/brand/ (SVG, with the wordmark converted to outlines).

The mark is a ship's load-line disc (Plimsoll mark) with a waterline through it; the wordmark is Fraunces
SemiBold. Requires: fonttools, brotli, uharfbuzz; the Fraunces woff2 from frontend/node_modules.
    python tools/brand/build_brand.py
"""

from io import BytesIO
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "frontend/node_modules/@fontsource-variable/fraunces/files/fraunces-latin-opsz-normal.woff2"
OUT = ROOT / "docs/brand"

INK, WAVE, WAVE_ON_DARK, WHITE = "#0f2d3a", "#1f8a5b", "#3fbf85", "#f3f6f7"
MASK_WAVE = "M0 34 C8 29 14 29 21 33.5 S33 38 40 33.5 S54 29 64 34"
WAVE_PATH = "M5 34 C11.5 30.1 16 30.1 22.2 33.8 S34.4 37.6 40.6 33.8 S52 30.1 59 33.3"


def mark(ring: str, wave: str, mask_id: str, transform: str = "") -> str:
    return (f'<g transform="{transform}"><mask id="{mask_id}"><rect width="64" height="64" fill="#fff"/>'
            f'<path d="{MASK_WAVE}" stroke="#000" stroke-width="10.5" fill="none"/></mask>'
            f'<circle cx="32" cy="32" r="18.5" fill="none" stroke="{ring}" stroke-width="5.2" mask="url(#{mask_id})"/>'
            f'<path d="{WAVE_PATH}" stroke="{wave}" stroke-width="4.6" stroke-linecap="round" fill="none"/></g>')


def wordmark_path(text: str, size: float) -> tuple[str, float, float]:
    """Outline `text` in Fraunces SemiBold; returns (path d in px, advance width, cap height) at font size `size`."""
    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": 600, "opsz": 48})
    buf = BytesIO()
    font.flavor = None
    font.save(buf)
    face = hb.Face(buf.getvalue())
    hbfont = hb.Font(face)
    hb_buf = hb.Buffer()
    hb_buf.add_str(text)
    hb_buf.guess_segment_properties()
    hb.shape(hbfont, hb_buf, {"kern": True, "liga": True})
    upem = font["head"].unitsPerEm
    scale = size / upem
    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    pen = SVGPathPen(glyphs)
    x = 0
    for info, pos in zip(hb_buf.glyph_infos, hb_buf.glyph_positions):
        name = order[info.codepoint]
        # font units -> px, flip y (baseline at y = 0)
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, (x + pos.x_offset) * scale, -pos.y_offset * scale)))
        x += pos.x_advance
    cap = font["OS/2"].sCapHeight * scale
    return pen.getCommands(), x * scale, cap


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, ring, wave in (("q-greenfleet-mark", INK, WAVE), ("q-greenfleet-mark-white", WHITE, WAVE_ON_DARK)):
        (OUT / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256">{mark(ring, wave, "m")}</svg>\n')

    size = 56.0
    d, width, cap = wordmark_path("Q-GreenFleet", size)
    mark_px = 88.0  # mark box; the ring is ~58 % of it, optically matched to the cap height
    gap = 14.0
    height = mark_px
    baseline = height / 2 + cap / 2
    total_w = mark_px + gap + width + 4
    for name, ring, wave, text in (("q-greenfleet-logo", INK, WAVE, INK), ("q-greenfleet-logo-white", WHITE, WAVE_ON_DARK, WHITE)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {height:.1f}" '
               f'width="{total_w:.0f}" height="{height:.0f}">'
               f'{mark(ring, wave, "m", f"scale({mark_px / 64:.4f})")}'
               f'<path transform="translate({mark_px + gap:.1f} {baseline:.1f})" fill="{text}" d="{d}"/></svg>\n')
        (OUT / f"{name}.svg").write_text(svg)
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
