# Creatures Structs

[Kaitai Struct](https://kaitai.io/) format descriptions for the Creatures
games. Use the [Kaitai Web IDE](https://ide.kaitai.io/) to load a `.ksy`
here alongside a real specimen and explore it interactively.

## Creatures 1

Every format below is a from-scratch rewrite, cross-checked against a live
Ghidra decompilation of the real `Creatures.exe`/`Injector.exe`/kit
executables -- not written from community documentation alone (though
community sources, this project's own openc2e reimplementation, and the
creatures.wiki GEN_files page were all used as a starting point and
cross-checked, with corrections noted inline where the real compiled code
disagreed with them). Every spec was compiled with the real
`kaitai-struct-compiler` and run against every real specimen shipped with
the game; **"byte-exact" below means the parse consumes the file to
EXACTLY the expected end position with zero unaccounted bytes**, not just
"doesn't crash."

| Format | File | Real specimens tested | Result |
| --- | --- | --- | --- |
| Exported creature | `c1exp.ksy` | 9 (`Aaron/Foxy/Nancy/Sid/Vixy/sandy/santa/santa2/dork.exp`, incl. a mature creature) | byte-exact, 0 remaining, all 9 |
| Genome | `c1gen.ksy` | 14 (`Genetics/{mum,dad}*.gen`, `Gren.GEN`, `TEST.GEN`) | all reach the real `gend` terminator cleanly; remaining bytes are confirmed zero-padding to a fixed file-allocation size, not a parse gap |
| Gene notes catalog | `c1gno.ksy` | 2 (`Genetics/{NORN,Grendel}.GNO`) | structurally confirmed against this project's own from-scratch reference parser (see Provenance) |
| Agent package | `c1cob.ksy` | 58 (24 `.COB` + 34 `.RCB`) | byte-exact, 0 remaining, all 58 |
| Sprite gallery (standard) | `c1spr.ksy` | 672 of 690 (see note below) | byte-exact, 0 remaining, all 672 |
| Default palette | `c1palette.ksy` | 2 (`Images/palette.dta`, `Palettes/palette.dta`) | byte-exact, 0 remaining, both |
| Standalone voice | `c1vce.ksy` | 3 (`male/female/grendel.vce`) | byte-exact to the documented 580+60-byte structure, all 3 |

An `.exp` file is exactly a `Creature` object followed immediately by a
`CGenome` object, back to back, with **no file header at all** -- the very
first two bytes of the file are already the start of the `Creature`
object. `c1exp.ksy`'s `genome` type is the exact same format as
`c1gen.ksy`'s root type (a standalone `.gen` file is just that payload
saved on its own).

### Known gaps, deliberately not modelled here

- **World.sfc** (the full saved-world document) is architecturally the
  same MFC-archive family as `.exp` but with a much larger, more varied
  object graph (creatures, scenery, lifts, bubbles, ...). Not yet ported
  to Kaitai Struct -- see this project's own from-scratch Python reference
  parser (below) if you need it now.
- **`.spr`'s "phased" sub-format** (18 of 690 real `.spr` specimens -- kit
  UI animation strips like the Science Kit dosage gauges) genuinely cannot
  be described in pure declarative Kaitai Struct: every real loader for it
  hardcodes how many image collections to read rather than storing a count
  in the file, so the only way to recover a given file's real collection
  count is a brute-force search for the value that lands exactly on EOF.
  `c1spr.ksy` documents this and covers the other 672 (non-phased)
  specimens fully.
- **`.att`** (body-part attachment points) is a plain whitespace-delimited
  ASCII text format, not a binary one -- not a good fit for Kaitai
  Struct's stream model, so not included here even though the format
  itself is fully closed (see the Python reference parser).
- **`.wav`** files are standard RIFF/WAVE audio -- already well covered by
  existing general-purpose Kaitai Struct specs elsewhere; not duplicated
  here.

## Provenance

Every format above (except `.GNO`, a CyberLife-internal authoring artifact
never read by any retail binary -- see `c1gno.ksy`'s own doc comment) was
verified against the real, compiled game code via a Ghidra decompilation
of `Creatures.exe` and all 12 official C1 kit executables, transcribed
here from an independent Python reference-parser suite that additionally
covers `World.sfc` in full, `.att`, `.wav`, and a few other formats not
included in this repo for the reasons above.
