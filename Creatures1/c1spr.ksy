meta:
  id: c1spr
  title: Creatures 1 sprite gallery, standard format (.spr)
  application: Creatures 1
  file-extension: spr
  endian: le
  license: CC0-1.0
doc: |
  The general-purpose C1 sprite gallery format: a flat frame-index table
  followed by raw 8bpp pixel data, one byte per pixel, indexed into
  Creatures 1's fixed default palette (not stored in the file). Used for
  body parts, UI chrome, COB toolbar pictures, and most other sprite
  content -- 672 of the 690 real `.spr` specimens shipped with the game
  (everything under `windows/Creatures/Images/*.spr` plus most top-level
  ones) are this format.

  Confirmed against a real, pre-existing comment on Creatures.exe's own
  `CGallery` constructor (0x004420c0) in a live Ghidra decompilation,
  cross-checked against a real specimen (`Images/i021.spr`) and
  independently against this project's own openc2e reimplementation
  (`openc2e/src/fileformats/sprImage.cpp`, `ReadSprFile`).

  IMPORTANT: **a second, structurally unrelated format also uses the
  `.spr` extension** in this game -- 18 specimens, all kit UI animation
  strips (the Dosage-gauge family, Gene.spr, Fertility.spr, LOBES.SPR,
  Hearts/AllNumbers/Gauge/Score/Time/Blink.spr), confirmed via dedicated
  loaders in Science Kit.exe and BiochemKit.exe. That "phased" format is
  deliberately NOT modelled here: every real loader for it hardcodes how
  many `CPhasedSprite` collections to read rather than storing a count in
  the file, so the only way this project's own reference parser
  (`tools/parse_spr.py`) determines a given phased file's real collection
  count is a brute-force search for the value that lands exactly on EOF --
  not something a purely declarative format description can express. Any
  tool consuming this `.ksy` should fall back to treating a `.spr` file
  that doesn't parse as this format as a candidate "phased" file and
  consult that reference parser.

  One further real oddity, confirmed 2026-08-22, worth knowing before
  treating every `.spr` on disk as one of these two formats:
  `Images/gren.SPR` (1092 bytes) is neither -- `frame_count=0` followed by
  1090 bytes of solid `0xCD`, the MSVC debug-heap "allocated, never
  initialized" fill pattern. A genuine unused placeholder file, not a
  third format.
seq:
  - id: num_frames
    type: u2
  - id: frames
    type: frame_header
    repeat: expr
    repeat-expr: num_frames
types:
  frame_header:
    seq:
      - id: data_offset
        type: u4
        doc: >
          Absolute byte offset (from the start of this file) where this
          frame's own pixel data starts. In a standalone single-gallery
          file this is simply contiguous with the header and any earlier
          frames' pixel data; the real engine's own multi-image gallery
          format lets several logical galleries share one physical file,
          which is what this field is really for.
      - id: width
        type: u2
      - id: height
        type: u2
    instances:
      pixels:
        pos: data_offset
        size: width.as<u4> * height.as<u4>
        doc: One byte per pixel, indexed into C1's fixed default palette.
