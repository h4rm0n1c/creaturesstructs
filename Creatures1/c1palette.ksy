meta:
  id: c1palette
  title: Creatures 1 fixed default palette (palette.dta)
  application: Creatures 1
  file-extension: dta
  endian: le
  license: CC0-1.0
doc: |
  Creatures 1's fixed 256-colour default palette -- every 8bpp sprite in
  the game (`.spr`, `.cob` toolbar pictures, ...) stores raw palette
  indices, not RGB, and indexes into this exact table
  (`windows/Creatures/Images/palette.dta` and
  `windows/Creatures/Palettes/palette.dta` are byte-identical, 768-byte
  copies of it).

  Confirmed two independent ways: byte-for-byte identical to this
  project's own openc2e reimplementation's hardcoded palette table
  (`openc2e/src/fileformats/c1defaultpalette.cpp`), and against the real
  compiled loader, `LoadPaletteDtaIntoBuffer` (0x00413b50 in
  `Creatures.exe`).

  Each channel is a raw 6-bit VGA DAC value (0-63, NOT 0-255) -- e.g.
  entry 1 is `3F 3F 3F` (63,63,63), the maximum 6-bit value, not
  `FF FF FF`. A consumer that needs real 0-255 RGB shifts each component
  left by 2 bits, confirmed directly from the real loader's own read loop.

  Real engine usage note (not itself a file-format fact -- the file has no
  header of any kind): `LoadPaletteDtaIntoBuffer` skips the FIRST 10
  entries and only realizes the remaining 236 into its live Windows system
  palette, a standard Win16/Win32 256-colour convention reserving low
  indices for the OS's own static system colours so the app's custom
  palette doesn't clobber them.
seq:
  - id: entries
    type: rgb_entry
    repeat: expr
    repeat-expr: 256
types:
  rgb_entry:
    seq:
      - id: r
        type: u1
      - id: g
        type: u1
      - id: b
        type: u1
