meta:
  id: c1egg
  title: LibreCreatures exported egg (.egg)
  application: LibreCreatures (Creatures 1)
  file-extension: egg
  endian: le
  license: CC0-1.0
doc: |
  An egg saved from a Creatures 1 world by LibreCreatures' File > Export
  Held Egg... and read back by File > Import Egg... . This is NOT a format of
  the 1996 game, which had no way to move an egg between worlds; it is
  defined by LibreCreatures (`creatures::Egg`, src/c1/creatures/egg.hpp) and
  built from the same MFC `CArchive` machinery the original uses for
  `World.sfc` and `.exp` files, so it reads like one of those.

  The file holds what makes the egg that egg, and nothing else:

    - its classifier. Any egg is accepted: family 2, genus 5, any species
      (norn eggs are 2 5 2). Import rejects anything else.
    - the sex the baby hatches as -- the egg's `obv1` (1 male, 2 female)
    - the baby's genome, whose source filename is the baby's moniker --
      the egg's `obv0`. The genes were crossed when the egg was made, so
      the genome is the child's own, not its parents'.

  Everything else about a live egg (its picture, hatch timer, pose,
  position) is deliberately left out: import makes a fresh full-size
  hatchery egg (random egg picture, pose 3, attr 67, a 2400-tick timer) and
  sets it down at spawn in the kitchen where the Hatchery leaves its eggs.
  If the moniker is already taken in the importing world -- by a creature,
  another egg, or a genome file holding different genes -- the baby gets a
  new moniker; the genes are unchanged. Export moves the egg out of its
  world, and import deletes the file, so an egg lives in one place at a
  time.

  ## Layout

  Like a `.exp`, there is no file header: the stream starts with an MFC
  object reference (see `c1exp.ksy` for the full tag scheme). The file is
  exactly one top-level object, a `CEgg`, whose last field is a nested
  object reference to its `CGenome`. In a file written by LibreCreatures
  both tags are always `0xFFFF` ("new class"), each with schema 1 and its
  class name, because each class appears once, so the layout is fixed. The
  `CGenome` record is the same one a `.exp` carries, byte for byte, and its
  payload is an ordinary `.gen` gene stream (`c1gen.ksy`).

  The `CEgg` header also records the genome's byte count and its CRC-32
  (the standard IEEE/zlib CRC over the payload bytes), so a reader can check
  a file completely before parsing it.

    offset  size  field
    0       2     0xFFFF  new-class tag
    2       2     1       schema
    4       2     4       class-name length
    6       4     "CEgg"
    10      4     version (2)
    14      4     classifier (event | species<<8 | genus<<16 | family<<24)
    18      4     sex (1 male, 2 female)
    22      4     genome size (n)
    26      4     CRC-32 of the n payload bytes
    30      2     0xFFFF  new-class tag
    32      2     1       schema
    34      2     7       class-name length
    36      7     "CGenome"
    43      4     payload size (n again)
    47      4     source filename -- the moniker, four ASCII letters or digits
    51      4     genome sex (1 male, 2 female; matches the egg's)
    55      1     life stage (0 for an egg)
    56      n     payload: the .gen gene stream, starting "gene"

  The file is exactly 56 + n bytes, and n is at most 1 MiB. LibreCreatures
  refuses a file unless every one of these holds before parsing any of it:
  the size is in range, both class records are exact, the version is 2,
  the classifier is an egg's, the sex is 1 or 2, both sizes equal n and the
  file is 56 + n bytes, the moniker is four ASCII letters or digits (it
  becomes a filename), the payload starts "gene", and the CRC matches.
  Version 1, which had no size or CRC, is no longer read. A later version
  may add fields after the CRC. `egg-format/README.md` explains all of this in prose,
  with a worked example. Tested byte-exact (zero bytes left over) against
  `c1egg.egg`, a norn egg exported from a running LibreCreatures world.
seq:
  - id: egg_tag
    contents: [0xff, 0xff]
  - id: egg_schema
    contents: [0x01, 0x00]
  - id: egg_class_name_length
    contents: [0x04, 0x00]
  - id: egg_class_name
    contents: "CEgg"
  - id: egg
    type: egg
types:
  egg:
    doc: The `CEgg` record (`creatures::Egg::serialize`).
    seq:
      - id: version
        type: u4
        valid: 2
      - id: classifier
        type: classifier
      - id: sex
        type: u4
        enum: sex
      - id: genome_size
        type: u4
        valid:
          max: 1048576
      - id: genome_crc32
        type: u4
        doc: >
          CRC-32 (IEEE 802.3, as zlib computes it) of the genome's payload
          bytes. Kaitai has no CRC; check it after parsing.
      - id: genome_tag
        contents: [0xff, 0xff]
      - id: genome_schema
        contents: [0x01, 0x00]
      - id: genome_class_name_length
        contents: [0x07, 0x00]
      - id: genome_class_name
        contents: "CGenome"
      - id: genome
        type: genome
  classifier:
    doc: >
      The egg object's packed classifier as the engine holds it. Any egg is
      family 2 genus 5; the species tells egg kinds apart (norn eggs are 2).
    seq:
      - id: event
        type: u1
      - id: species
        type: u1
      - id: genus
        type: u1
        valid: 5
      - id: family
        type: u1
        valid: 2
  genome:
    doc: >
      The `CGenome` record, identical to the one in a `.exp`
      (`CGenome::Serialize` @ 0x004185c0).
    seq:
      - id: payload_size
        type: u4
        valid: _parent.genome_size
      - id: moniker
        type: str
        encoding: ascii
        size: 4
        doc: >
          The genome's source filename: the baby's moniker, and the name of
          its `<moniker>.gen` in the world's Genetics folder.
      - id: genome_sex
        type: u4
        enum: sex
      - id: life_stage
        type: u1
      - id: payload
        size: payload_size
        doc: A `.gen` gene stream (see `c1gen.ksy`).
enums:
  sex:
    1: male
    2: female
