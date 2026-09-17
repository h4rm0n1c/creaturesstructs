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
  A Creatures 1 `.cob` (Creatures OBject) file packages injectable world
  objects -- toys, food, gadgets, seasonal decorations -- as CAOS scripts plus
  a toolbar picture, for an injector kit to apply to a running world. A `.rcb`
  ("removal COB") has the identical layout and undoes its paired `.cob`.

  There is no MFC object-tag framing: the file is a count followed by that
  many flat records. Strings use MFC's CString length prefix.

  PROVENANCE. The retail game never reads these files; only an injector kit
  does. The one compiled loader available is `LoadInjectorCobFile`
  (0x00408370) in the Community Edition's `Injector.exe` -- an mfc140 rebuild,
  not a 1996 binary. This spec follows that loader field for field, and is
  byte-exact against all 24 shipped `.COB` and 34 shipped `.RCB` specimens.
  openc2e (`src/fileformats/c1cobfile.cpp`) reads the same bytes with a
  narrower model; where the two differ, the shipped specimens cannot tell them
  apart, because every one holds exactly one record with an empty description.
  The loader is the stronger evidence, and its model explains two bytes
  openc2e's leaves unexplained:

  1. The leading u2 is a RECORD COUNT, not a version. The loader reads it
     and loops that many times, appending one object per record. openc2e
     requires it to equal 1 and calls it `version`; every specimen holds 1.
  2. Each record ends with a second string, `description`, shown in the
     injector's description box ("No description available." when empty).
     openc2e stops after `name`. In every specimen it is empty -- a single
     zero length byte -- which is the "trailing NUL" earlier revisions of this
     spec modelled as an unexplained constant.

  THE TWO SCRIPT ARRAYS. Read from `CAgentsPage::InjectSelectedCob`
  (0x00405e60) and `RemoveSelectedCob` (0x00406220), and confirmed live by
  injecting "Cage Control Box" into a running world and logging every CAOS
  script the kit sent:

  - `object_scripts` run in full, in order, every time the record is applied.
    In a `.cob` these are the object's event scripts, each a
    `scrp family genus species event,...` definition (`scrp 2 3 14 1,...`
    for the Cage Control Box).
  - `activation_scripts` are the action itself. In a `.cob` that is the
    `inst,new: simp ...,endm` that creates the object (`inst,new: simp cbox
    2 0 9000 0,...`); in a `.rcb` it is the removal (`inst,enum 2 3 14,kill
    targ,next,scrx 2 3 14 1,endm`), with `object_scripts` empty. Which of them
    run depends on `activation_mode`.

  Removal applies the paired `.rcb` through the same loader and runs both
  arrays in the same order, so injection and removal are one mechanism.

  An earlier revision of this spec named these arrays the other way round --
  `install_scripts` and a rotating set of `removal_scripts` -- following
  Ghidra field names that turned out to be guesses. openc2e's names
  (`object_scripts`, `install_scripts`) had the roles right; `activation_scripts`
  is used here because a `.rcb`'s second array removes rather than installs.
seq:
  - id: num_records
    type: u2
    doc: >
      Number of records that follow. The loader loops on this; openc2e reads
      it as a version and requires 1. All shipped specimens hold 1.
  - id: records
    type: record
    repeat: expr
    repeat-expr: num_records
types:
  record:
    seq:
      - id: quantity_available
        type: u2
        doc: >
          Injections remaining. Per the CE Injector: 0 and every value >= 255
          mean unlimited -- `CAgentsPage::UpdateSelectedCobUi` (0x00405c50)
          displays "Infinite" for both, and `InjectSelectedCob` never
          decrements them. Values 1..254 count down by one per injection in
          `one_per_activation` mode (and drop straight to 0 in any other
          mode). The count lives in memory only; the kit never writes it back
          to the file. Consequence worth knowing: a 1-use object decrements to
          0 and is then unlimited for the rest of the session.
      - id: expiration_month
        type: u4
      - id: expiration_day
        type: u4
      - id: expiration_year
        type: u4
        doc: >
          `CCobObject::IsExpired` (0x00408100): all three zero means the
          record never expires (every shipped specimen). Otherwise day is
          clamped to 1..31, month to 1..12, a year <= 99 means 1900 + year,
          and the record stays valid through 23:59:59 local time on that
          date.
      - id: num_object_scripts
        type: u2
      - id: num_activation_scripts
        type: u2
      - id: activation_cursor
        type: u2
        doc: >
          How many activations have been used, advanced by
          `InjectSelectedCob`. openc2e reads this u2 and the next as one u32
          `quantity_used`; the loader reads two u2 fields. Zero in every
          specimen.
      - id: activation_mode
        type: u2
        enum: activation_mode
        doc: >
          Zero in every specimen. Mode 0 runs ONE activation script per
          injection, walking the array from its last entry backwards
          (index = num_activation_scripts - activation_cursor - 1, clamped
          at 0) and then advancing the cursor. Any other value runs every
          activation script, sets the cursor to the array length, and
          zeroes a limited quantity.
      - id: object_scripts
        type: mfc_string
        repeat: expr
        repeat-expr: num_object_scripts
        doc: Run in full, in order, every time the record is applied.
      - id: activation_scripts
        type: mfc_string
        repeat: expr
        repeat-expr: num_activation_scripts
        doc: >
          The action -- object creation in a `.cob`, removal in a `.rcb`.
          Before injecting, the kit scans these for the token `norn` and, if
          present, refuses to proceed without a selected creature.
      - id: picture_width
        type: u4
      - id: picture_height
        type: u4
      - id: picture_row_stride
        type: u2
        doc: >
          `CSprite::Serialize` (0x0040d660) reads this as the sprite's row
          stride in bytes, stored as u16. For these 8bpp pictures it equals
          `picture_width` in every shipped specimen; openc2e notes one
          community file (`ABK- Egg Gender.cob`) with 0. Kept raw.
      - id: picture_data
        size: picture_width * picture_height
        if: picture_width > 0 and picture_height > 0
        doc: >
          8bpp, indexed into C1's fixed default palette (not stored in the
          file). Rows are stored BOTTOM-TO-TOP: the first row in the stream is
          the image's last scanline. `.rcb` files carry a 0x0 picture.
      - id: name
        type: mfc_string
        doc: The object's name as shown in the injector's list.
      - id: description
        type: mfc_string
        doc: >
          Free text for the injector's description box. Empty (one zero
          length byte) in every shipped specimen.
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
enums:
  activation_mode:
    0: one_per_activation
