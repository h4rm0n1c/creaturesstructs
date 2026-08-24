# Python reference parsers

Stdlib-only (except `render_world_background.py`, which needs
[Pillow](https://pypi.org/project/Pillow/)). This is the actual source
the `.ksy` specs were transcribed from -- if one ever disagrees with its
matching module here, trust the Python.

Each module runs standalone (`python3 parse_cob.py <path>`) and prints a
confirmation log ending in `CONFIRMED` or a `STOPPED` diagnostic naming
the exact byte offset that didn't match.

| Module | Format | Notes |
| --- | --- | --- |
| `parse_sfc.py` | `World.sfc`, `.exp` | No Kaitai equivalent for `World.sfc` -- see top-level README. |
| `parse_gene.py` | `.gen`, and `.exp`'s embedded genome | |
| `parse_gno.py` | `.GNO` gene notes | |
| `parse_cob.py` | `.cob`/`.rcb` | |
| `parse_spr.py` | `.spr`, both variants | Also handles the "phased" sub-format `.ksy` can't. |
| `parse_palette.py` | `palette.dta` | |
| `parse_vce.py` | `.vce` | |
| `parse_health_shop_items.py` | `Health`, `Aphro` | |
| `parse_att.py` | `.att` | Plain text, no `.ksy` equivalent. |
| `parse_wav.py` | C1's `.wav` files | Checks against the real engine's loader, not generic RIFF. |
| `render_world_background.py` | -- | Renders a `World.sfc` background + room overlay to PNG. |

![World.sfc background with room boundaries drawn on top](sample-output/world_background_rooms_preview.png)

## Provenance

Verified against the real compiled game (Ghidra decompilation of
`Creatures.exe` and the C1 kits), cited by function name and address in
each module's docstring. `.GNO` is the one exception -- a CyberLife
authoring tool never read by the retail game, so there's no compiled
code to check it against.
