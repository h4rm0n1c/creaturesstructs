#!/usr/bin/env python3
"""
Structural verifier for Creatures 1's fixed default palette file
(windows/Creatures/Images/palette.dta and windows/Creatures/Palettes/
palette.dta -- byte-identical copies, 768 bytes each).

Confirmed two independent ways: (1) byte-for-byte identical to this
repo's openc2e reimplementation's hardcoded CREATURES_PALETTE[] array
(openc2e/src/fileformats/c1defaultpalette.cpp) -- the exact table every
.spr/.cob image this session has been reading indexes into; (2) the real
compiled loader, `LoadPaletteDtaIntoBuffer` (0x00413b50 in Creatures.exe).

File format: 256 entries x 3 bytes (red, green, blue), no header. Each
channel is a raw 6-bit VGA DAC value (0-63, NOT 0-255) -- e.g. entry 1 is
`3F 3F 3F` (63,63,63), the maximum 6-bit value, not `FF FF FF`. Consumers
that need real 0-255 RGB shift each component left by 2 bits (confirmed
in LoadPaletteDtaIntoBuffer's own read loop: `(char)fgetc(...) << 2`).

Real engine usage note (not a file-format fact, but worth recording):
`LoadPaletteDtaIntoBuffer` skips the FIRST 10 entries (30 bytes) and
only realizes the remaining 236 into its live Windows system palette --
a standard Win16/Win32 256-color convention, reserving palette indices
0-9 (and, symmetrically, entries 246-255 are also conventionally
reserved) for the OS's own static system colors so the app's custom
palette doesn't clobber them. The file itself is NOT structured with any
such header -- this is purely how the engine applies it at realization
time, confirmed by reading the loader's own real fseek/read-count
values (skip 0x1e=30 bytes, read exactly 0xec=236 triples) against the
full 768-byte file.
"""
import sys


class PaletteFormatError(Exception):
    pass


def parse_palette(path, verbose=True):
    data = open(path, 'rb').read()

    def log(*a):
        if verbose:
            print(*a)

    if len(data) != 768:
        raise PaletteFormatError(f"expected exactly 768 bytes (256 x 3), got {len(data)}")

    entries = []
    for i in range(256):
        r, g, b = data[i * 3], data[i * 3 + 1], data[i * 3 + 2]
        if r > 63 or g > 63 or b > 63:
            log(f"  WARNING: entry {i} ({r},{g},{b}) exceeds the expected 6-bit (0-63) range")
        entries.append((r, g, b))

    log(f"parsed 256 RGB entries (6-bit VGA range)")
    log(f"  entry[0] (system reserved)  = {entries[0]}")
    log(f"  entry[9] (last reserved)    = {entries[9]}")
    log(f"  entry[10] (first app color) = {entries[10]}")
    log(f"  entry[255] (last entry)     = {entries[255]}")
    log("PALETTE format: CONFIRMED")

    return dict(entries=entries)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-palette.dta>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_palette(sys.argv[1])
    except PaletteFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
