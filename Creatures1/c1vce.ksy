meta:
  id: c1vce
  title: Creatures 1 standalone voice file (.vce)
  application: Creatures 1
  file-extension: vce
  endian: le
  license: CC0-1.0
doc: |
  A standalone C1 speech-synthesis voice bank (the 3 real specimens
  shipped with the game: `male.vce`, `female.vce`, `grendel.vce`) --
  32 syllable sound-file/duration records plus 81 trigram-selection
  bitmasks, feeding an English-text-to-syllable-sequence algorithm
  documented in this project's own openc2e reimplementation
  (`openc2e/src/openc2e/VoiceData.cpp`, `NextSyllableFor`; not
  reimplemented here, since this spec's job is the file's structure, not
  runtime speech synthesis).

  Confirmed two independent ways: cross-checked against that openc2e
  model, and against the real compiled loader, `Voice::LoadVoiceFile`
  (0x004454e0 in `Creatures.exe`) -- via raw disassembly, since this
  function's own Ghidra decompile text is unreliable (a genuine decompiler
  artifact).

  IMPORTANT: this is the OPPOSITE field order from the same 580-byte
  payload as archived inside a `.exp` file's embedded `Creature` record
  (see `c1exp.ksy`'s `voice_tail`, masks-first) -- confirmed via
  disassembly of both loaders, a real and independent divergence between
  the standalone-file and archived-in-`.exp` Voice formats, not a bug in
  either.
seq:
  - id: sounds
    type: sound_record
    repeat: expr
    repeat-expr: 32
    doc: >
      Slots 0-3 are blank (all-zero sound_id) in every real specimen --
      "between words" delay-only slots, per openc2e's algorithm
      documentation.
  - id: trigram_selection_masks
    type: u4
    repeat: expr
    repeat-expr: 81
    doc: 3 letter-position tables (26 letters + 1 blank/space) x 27 entries each.
  - id: trailing_data
    size: 60
    doc: >
      Present, byte-identical, in all 3 real specimens (male/female/grendel)
      -- too consistent across independently-authored files to be leftover
      heap noise, so genuinely real fixed data, but confirmed via
      disassembly of Voice::LoadVoiceFile to NOT be read by the retail
      engine at all (its own cleanup happens immediately after byte 580).
      Likely a fixed artifact of whatever internal authoring tool wrote
      these files; not decoded further here.
types:
  sound_record:
    doc: C1VoiceSoundArchiveRecord (real Ghidra-recovered struct).
    seq:
      - id: sound_id
        type: str
        encoding: ascii
        size: 4
      - id: duration
        type: u4
