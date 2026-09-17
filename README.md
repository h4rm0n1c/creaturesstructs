# Creatures Structs

[Kaitai Struct](https://kaitai.io/) format descriptions for the Creatures
games. Load a `.ksy` here into the [Kaitai Web IDE](https://ide.kaitai.io/)
alongside a real specimen to explore it.

## Creatures 1

All specs below are reverse-engineered from the real compiled game
(Ghidra decompilation of `Creatures.exe` and the C1 kit executables), and
tested with the real `kaitai-struct-compiler` against every real specimen
shipped with the game. "Byte-exact" means zero bytes left over after
parsing, not just "didn't crash."

| Format | Spec | Specimens | Result |
| --- | --- | --- | --- |
| Exported creature | `c1exp.ksy` | 9 `.exp` files | byte-exact |
| Genome | `c1gen.ksy` | 14 `.gen` files | byte-exact to terminator |
| Gene notes catalog | `c1gno.ksy` | 2 `.GNO` files | confirmed |
| Agent package | `c1cob.ksy` | 58 `.cob`/`.rcb` files | byte-exact |
| Sprite gallery (standard) | `c1spr.ksy` | 672 of 690 `.spr` files | byte-exact |
| Default palette | `c1palette.ksy` | 2 `palette.dta` files | byte-exact |
| Standalone voice | `c1vce.ksy` | 3 `.vce` files | byte-exact |
| Kit shop item catalog | `c1shopitems.ksy` | `Health`, `Aphro` | byte-exact |

A `.exp` file is just a `Creature` object followed by a `CGenome` object,
back to back, no file header. `c1gen.ksy` is the same format as that
`CGenome`'s payload.

## Python reference parsers

`Creatures1/python-reference/` has the full Python source these specs
were built from, plus formats with no Kaitai equivalent (see below) --
including a tool that renders a `World.sfc`'s background and rooms to
PNG. See that folder's README.

## Kit protocol

`Creatures1/kit-protocol/` documents how the kits (Hatchery, Science Kit,
Injector, ...) talk to the game -- a live IPC protocol rather than a file
format, so there's no `.ksy` for it. Every game-to-kit message turns out to
be one OLE automation call named `Communicate`, carrying a packed header and
a payload; kits answer through the game's `SFC.OLE` object, a five-method
`Macro` conversation over a byte-length BSTR. Also covers registration, the
Tools-menu slot policy, and the named-pipe bridge the Community Edition uses
under Wine. Includes `generic_kit.cpp`, a headless kit the game will launch
from its own Tools menu that logs everything asked of it, and
`sfc_ole_client.cpp`, which queries the running game the way a kit does. See
that folder's README.

## DDE service

`Creatures1/dde-service/` documents the game's second external interface: a
Windows DDEML service named `Vivarium`, separate from the kits' `SFC.OLE`. It
runs CAOS for a client and answers four request items -- macro output, a brain
activity map (three characters per active neuron, five report modes), an
unused `BrainWiring` slot, and fourteen engine counters. Covers every
transaction, the per-conversation macro state that carries `targ` and `var0`/
`var1` between an `EXECUTE` and a request, exact reply byte counts, and three
requests that crash the original. Includes `vivarium_client.cpp`. See that
folder's README.

## What's not here, and why

- **World.sfc** -- can't be a pure Kaitai spec. Its object arrays reuse
  MFC classes by numeric back-reference with no name in the stream (e.g.
  `Scenery` is named once, then reused 139 more times); resolving that
  needs a live class registry, which Kaitai's `switch-on` has no way to
  express. Fully covered in `python-reference/parse_sfc.py` instead.
- **`.spr`'s "phased" sub-format** (18 of 690 files) -- no real loader
  stores its collection count on disk, so it's only recoverable by
  brute-force search. `c1spr.ksy` covers the other 672 fine.
- **`.att`** -- plain text, not binary. See `parse_att.py`.
- **`.wav`** -- standard RIFF, already covered by other Kaitai specs.
  `parse_wav.py` is included anyway since it checks a file against C1's
  actual loader behavior, not generic RIFF validity.
- **The kit protocol and the DDE service** -- IPC, not file formats.
  Documented in `Creatures1/kit-protocol/` and `Creatures1/dde-service/`.

## Provenance

Every format here (except `.GNO`, a CyberLife authoring tool never read
by the retail game) was verified against the real compiled game code,
not just community docs. See each `.ksy`'s own doc comment for specifics
and citations.

One exception in kind: the retail game never reads `.cob`/`.rcb` files, so
`c1cob.ksy` follows the only compiled loader available -- the Community
Edition's `Injector.exe`, an mfc140 rebuild rather than a 1996 binary.
Where it and openc2e disagree, the shipped specimens can't arbitrate (every
one holds a single record with an empty description); the spec says so
field by field.
