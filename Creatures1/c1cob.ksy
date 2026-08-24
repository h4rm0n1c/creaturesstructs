meta:
  id: c1cob
  title: Creatures 1 agent package (.cob / .rcb)
  application: Creatures 1
  file-extension:
    - cob
    - rcb
  endian: le
  license: CC0-1.0
doc: |
  A Creatures 1 `.cob` (Creatures OBject) file packages one injectable
  world object -- toy, food, gadget, seasonal decoration -- along with its
  install/removal CAOS scripts and its toolbar icon, ready for `Injector.exe`
  to install into a running world. `.rcb` ("removal COB") files are
  structurally IDENTICAL to `.cob` -- confirmed via Injector.exe's real
  `.rcb` loader (`CAgentsPage::RemoveSelectedCob`), which calls the exact
  same `LoadInjectorCobFile` routine used for `.cob`, with no separate
  format. This has no MFC object-tag framing at all (unlike `.exp`/
  `.sfc`) -- it's a plain flat record, version 1 only (C1's `.cob` format
  has no version 2; that name is reused, incompatibly, by Creatures 2).

  This spec's field layout is sourced from this project's own openc2e
  reimplementation (`openc2e/src/fileformats/c1cobfile.cpp`), a mature,
  independently community-maintained C1/C2/C3 engine, then corrected and
  extended against a live Ghidra decompilation of `Creatures.exe`'s real
  `Injector.exe`'s own `LoadInjectorCobFile` (0x00408370) and confirmed
  byte-exact against all 24 real `.COB` and 34 real `.RCB` specimens
  shipped with the game. Two corrections versus the plain openc2e model,
  both confirmed directly from the real compiled loader rather than
  guessed:

  1. What openc2e reads as one `quantity_used: u32` is really two
     separate `u16` fields in the real compiled reader -- see
     `next_removal_script_index`/`script_execution_mode` below. (All 24
     real specimens happen to have both halves zero, so this can't be
     independently confirmed from data alone -- but the compiled engine's
     own field-by-field read is stronger evidence than an untested
     32-bit guess.)
  2. The two script arrays' REAL behavioral roles are the reverse of
     what their on-disk field names suggest, confirmed via Injector.exe's
     `InjectSelectedCob` (0x00405e60): the array most people would call
     "object_scripts" is actually the set of scripts run ONCE at install
     time (each one a `scrp family genus species event` classifier
     declaration -- confirmed present at the very start of `[0]` in every
     real specimen), while the array most naturally read as
     "install_scripts" is actually a ROTATING set of removal scripts, one
     of which runs per activation/removal, advancing
     `next_removal_script_index` each time.

  This project also found (2026-08-22) a genuine on-disk trailing NUL
  byte after `name`, present as the literal last byte of all 24 real
  `.COB` specimens with zero exceptions -- not modelled by openc2e's own
  reader (which doesn't check for it) but real all the same.
seq:
  - id: version
    type: u2
    valid: 1
    doc: Only version 1 exists in real C1 data; C2's incompatible format reuses this extension.
  - id: quantity_available
    type: u2
    doc: Vending-machine-style stock limit; 0xFFFF/large values typically mean unlimited in practice.
  - id: expiration_month
    type: u4
  - id: expiration_day
    type: u4
  - id: expiration_year
    type: u4
  - id: num_install_scripts
    type: u2
    doc: >
      Despite the natural reading, this is the count of scripts run ONCE
      at install time (see this spec's own doc header) -- confirmed via
      Injector.exe's real InjectSelectedCob.
  - id: num_removal_scripts
    type: u2
    doc: Count of the rotating one-per-activation removal scripts (see doc header).
  - id: next_removal_script_index
    type: u2
    doc: >
      Real name/split confirmed via Injector.exe's compiled
      LoadInjectorCobFile, which reads this as its own u16 field (openc2e
      instead reads this 4-byte region as one u32 "quantity_used").
  - id: script_execution_mode
    type: u2
    doc: A real enum in Injector.exe; ONE_REMOVAL_SCRIPT_PER_ACTIVATION is a confirmed member.
  - id: install_scripts
    type: mfc_string
    repeat: expr
    repeat-expr: num_install_scripts
    doc: >
      The on-disk field usually called "object_scripts" -- run ONCE, the
      moment the object is installed into the world. Each one starts with
      a `scrp family genus species event` classifier declaration in every
      real specimen -- these are per-classifier event handlers, installed
      once and triggered by the game's event dispatcher for the object's
      lifetime.
  - id: removal_scripts
    type: mfc_string
    repeat: expr
    repeat-expr: num_removal_scripts
    doc: >
      The on-disk field usually called "install_scripts" -- really a
      rotating set, one script run per activation/removal, advancing
      `next_removal_script_index` each time (mode-dependent). For a real
      `.rcb` file this is typically empty, and the paired `.cob`'s uninstall
      command(s) live here instead, run after any `install_scripts`.
  - id: picture_width
    type: u4
  - id: picture_height
    type: u4
  - id: picture_width_check
    type: u2
    doc: >
      Matches picture_width in every real specimen seen in this repo
      (kept raw, not asserted -- at least one known community specimen
      reportedly has 0 here instead).
  - id: picture_data
    size: picture_width.as<u4> * picture_height.as<u4>
    if: picture_width > 0 and picture_height > 0
    doc: >
      One row at a time, 8bpp, indexed into C1's fixed default palette
      (not stored in the file) -- but rows are stored BOTTOM-TO-TOP (row 0
      in the byte stream is the image's LAST scanline), a classic
      bottom-up-DIB convention.
  - id: name
    type: mfc_string
    doc: The object's real in-game name, as shown in the Objects toolbar.
  - id: trailing_nul
    type: u1
    valid: 0
    doc: >
      A real on-disk NUL terminator after `name`, confirmed present as the
      literal last byte of all 24 real .COB specimens in this repo with
      zero exceptions -- not modelled by the openc2e reference
      implementation this spec is otherwise based on.
types:
  mfc_string:
    doc: >
      Length-prefixed string: 1-byte length; if that byte is 0xFF (255), an
      additional u2 gives the real length (the same convention MFC's own
      CArchive CString serialization uses, reused here even though this
      format has no surrounding MFC object-tag framing).
    seq:
      - id: length1
        type: u1
      - id: length2
        type: u2
        if: length1 == 0xff
      - id: text
        type: str
        encoding: ascii
        size: 'length1 != 0xff ? length1 : length2'
