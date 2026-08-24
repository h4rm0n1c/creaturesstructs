#!/usr/bin/env python3
"""
Renders a Creatures 1 World.sfc save's background composite to a real
PNG image, and a second copy with every MapData room RECT drawn on top --
built on top of this project's own confirmed parse_sfc.py/parse_spr.py/
parse_palette.py reference parsers, not a separate reverse-engineering
pass.

MapData's `gallery` field (see parse_sfc.py's parse_cgallery /
parse_mapdata) does NOT embed pixel data in World.sfc itself -- each
CImage record only carries a width/height/sprite_data_offset triple. The
actual pixel bytes live in a separate, paired `.spr` file named by the
gallery's own `sprite_file_id` (this repo's specimen: "Back", i.e.
`windows/Creatures/Images/back.spr`) -- confirmed by cross-referencing
`sprite_data_offset` against that file's own frame table in
tools/parse_spr.py's FORMAT 1 layout and finding every offset lands
exactly on a real frame boundary.

TILE ORDER, confirmed 2026-08-22 by brute-force comparing both plausible
readings against the real image content (a garbled-vs-coherent visual
check, recorded here since it isn't otherwise derivable from either file
alone): World.sfc's `worldpopulated` specimen has a 464-frame gallery
covering a 58x8 tile grid (144x150 px/tile), and the frames are laid out
COLUMN-MAJOR (`col, row = frame_index // rows, frame_index % rows`), not
the more naively-expected row-major order.

Room RECTs come directly from MapData's own `rooms` array (see
parse_mapdata) -- real world-pixel-coordinate rectangles, room_type in
{0,1,2,...} (colour-coded here; a 4th+ type not seen in this repo's
specimens falls back to green).

Usage:
    python3 render_world_background.py <path-to-World.sfc> <path-to-back.spr> <path-to-palette.dta> <output-dir>

Requires Pillow (`pip install Pillow`), unlike every other tool in this
suite (which are stdlib-only).
"""
import io
import os
import sys
import contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_sfc import parse_sfc
from parse_spr import parse_spr
from parse_palette import parse_palette

ROOM_TYPE_COLORS = {0: (255, 40, 40), 1: (40, 180, 255), 2: (255, 220, 0)}
DEFAULT_ROOM_TYPE_COLOR = (0, 255, 0)


def _quietly(fn, *args):
    """Every parser in this suite prints a verbose structural-confirmation
    log by default -- silence it here so this tool's own output stays
    readable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*args)


def build_palette_table(palette_path):
    """Returns a flat 768-byte PIL 'P'-mode palette table (256 x RGB),
    converting each 6-bit VGA DAC channel (see parse_palette.py) to real
    8-bit range with the same `<< 2` shift the real engine uses."""
    pal = _quietly(parse_palette, palette_path)
    flat = []
    for r, g, b in pal['entries']:
        flat.extend([r << 2, g << 2, b << 2])
    while len(flat) < 768:
        flat.append(0)
    return flat


def render_background(sfc_path, spr_path, palette_path, cols=None, rows=None):
    """Returns (PIL.Image in RGB mode, the parsed `world` dict) for the
    world's background composite.

    `cols`/`rows` (the background tile grid shape) default to 58x8, the
    confirmed real shape for this repo's own 464-frame `worldpopulated`
    specimen -- the ONLY specimen this has been checked against. There is
    no confirmed general rule for deriving a different world's grid shape
    from its file contents alone (frame_count factors in more than one
    plausible way in general); pass the real shape explicitly for any
    other World.sfc, e.g. by dividing the paired .spr's total pixel-data
    span by one tile's byte size and checking the result against the
    world's real known dimensions."""
    from PIL import Image

    world = _quietly(parse_sfc, sfc_path)
    spr = _quietly(parse_spr, spr_path)
    flat_pal = build_palette_table(palette_path)

    gallery = world['mapdata']['gallery']
    tile_w = spr['frames'][0]['width']
    tile_h = spr['frames'][0]['height']
    if any(f['width'] != tile_w or f['height'] != tile_h for f in spr['frames']):
        raise ValueError("this tool assumes a uniform tile size; the given "
                          ".spr has mixed frame dimensions and needs a "
                          "different layout strategy")
    if len(spr['frames']) != gallery['image_count']:
        raise ValueError(f"gallery declares {gallery['image_count']} images "
                          f"but the .spr has {len(spr['frames'])} frames -- "
                          f"wrong .spr file for this World.sfc?")

    if cols is None and rows is None:
        cols, rows = 58, 8
        if len(spr['frames']) != cols * rows:
            raise ValueError(
                f"this .spr has {len(spr['frames'])} frames, not the "
                f"58x8=464 this tool's default grid shape assumes -- pass "
                f"cols=/rows= explicitly for this specimen (see this "
                f"function's own docstring)")
    elif cols is None or rows is None:
        raise ValueError("pass both cols and rows, or neither")

    canvas = Image.new('P', (cols * tile_w, rows * tile_h))
    canvas.putpalette(flat_pal)
    for frame in spr['frames']:
        idx = frame['index']
        col, row = idx // rows, idx % rows  # confirmed real order: column-major
        tile = Image.frombytes('P', (tile_w, tile_h), frame['data'])
        tile.putpalette(flat_pal)
        canvas.paste(tile, (col * tile_w, row * tile_h))

    return canvas.convert('RGB'), world


def draw_rooms(background, world, outline_width=1):
    """Returns a copy of `background` with every MapData room RECT drawn
    on top, colour-coded by room_type and labelled "index:type"."""
    from PIL import ImageDraw

    overlay = background.copy()
    draw = ImageDraw.Draw(overlay)
    for i, (left, top, right, bottom, room_type) in enumerate(world['mapdata']['rooms']):
        color = ROOM_TYPE_COLORS.get(room_type, DEFAULT_ROOM_TYPE_COLOR)
        draw.rectangle([left, top, right, bottom], outline=color, width=outline_width)
        draw.text((left + 3, top + 1), f"{i}:{room_type}", fill=color)
    return overlay


def main():
    if len(sys.argv) not in (5, 7):
        print(f"usage: {sys.argv[0]} <World.sfc> <back.spr> <palette.dta> <output-dir> "
              f"[<cols> <rows>]", file=sys.stderr)
        sys.exit(1)
    sfc_path, spr_path, palette_path, out_dir = sys.argv[1:5]
    cols, rows = (int(sys.argv[5]), int(sys.argv[6])) if len(sys.argv) == 7 else (None, None)
    os.makedirs(out_dir, exist_ok=True)

    background, world = render_background(sfc_path, spr_path, palette_path, cols, rows)
    bg_path = os.path.join(out_dir, 'world_background.png')
    background.save(bg_path)
    print(f"saved {bg_path} ({background.size[0]}x{background.size[1]})")

    overlay = draw_rooms(background, world)
    rooms_path = os.path.join(out_dir, 'world_background_rooms.png')
    overlay.save(rooms_path)
    print(f"saved {rooms_path} ({len(world['mapdata']['rooms'])} rooms drawn)")


if __name__ == '__main__':
    main()
