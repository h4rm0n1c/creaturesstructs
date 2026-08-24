meta:
  id: c1shopitems
  title: Creatures 1 kit shop/dispenser item catalog (Health, Aphro)
  application: Creatures 1 (Health Kit / Breeder's Kit)
  endian: le
  license: CC0-1.0
doc: |
  A private, single-purpose item catalog used by two official C1 kits'
  "Add Object" shop dialogs: `windows/Creatures/Health` (Health Kit.exe,
  3 real items -- Feverfew, Morning Glory, Cheese) and
  `windows/Creatures/Aphro` (Breeders_Kit.exe, 2 real items -- Tomato, Ugly
  Tomato). Both files ship with no extension. NOT the same format as
  `.cob`/`.rcb` (see `c1cob.ksy` -- no version/quantity_available/expiry
  fields here) and not a COB-embedded picture either.

  Confirmed byte-exact against both real specimens (0 bytes remaining in
  each), cross-checked against real compiled code in three places:
  `CShopItem::SerializeHealthSpriteRecord` (0x00410740, Health Kit.exe --
  `CShopItem`'s own vtable override of the base
  `HealthAudioBase::SerializeSpriteData`), `HealthAudioBase::
  SerializeSpriteData` (0x00408750, its `mode_flags & 1` load/store branch
  confirmed to match real MFC `CArchive::Mode`), and
  `CSprite::SerializeBitmapData` (0x0040e6c0, confirmed via raw
  disassembly).

  REAL TRAP FOUND AND AVOIDED while first closing this format (worth
  knowing if you're verifying it independently): a naive "scan for a
  printable-ASCII run" read of the raw bytes strongly suggested
  `health_command_string` was NUL-terminated raw text -- it is not. Every
  string field uses the ordinary MFC 1-byte length-prefixed CString wire
  format. The trap: one real item's `health_command_string` has length
  0x5F (95), which is ALSO the ASCII code for `_` -- the command text's
  own real first character -- so a naive scan silently absorbed the
  length byte as if it were content, making the string look 2 bytes
  longer and coincidentally NUL-terminated by the following sprite
  header's `row_stride` low byte (0x20, a printable space). Always locate
  a real, unique anchor string (here: a literal display name like
  "Feverfew") and solve backwards/forwards from it before trusting a raw
  byte-shape guess on an unfamiliar format.
seq:
  - id: num_items
    type: u2
  - id: items
    type: shop_item
    repeat: expr
    repeat-expr: num_items
types:
  shop_item:
    seq:
      - id: remaining_quantity
        type: u2
        doc: >
          Observed as 12 in every real item across both specimens --
          meaning/use not investigated further; may be an
          "always available" sentinel rather than a live stock counter.
      - id: install_command
        type: mfc_string
        doc: >
          The real CAOS install command for this item, e.g. "inst,new:
          simp herb 3 0 3500 0,setv clas 33819136,setv attr 67,bhvr 0
          1,setv obv0 1,pose 2,edit" -- no leading "_"; the game
          presumably prepends the literal INST-block delimiter at use
          time, which is not itself stored in the file.
      - id: row_stride_bytes
        type: u4
      - id: height
        type: u4
      - id: width
        type: u2
      - id: pixel_data
        size: row_stride_bytes.as<u4> * height.as<u4>
        doc: >
          This item's dispenser-icon sprite, 8bpp, indexed (C1's fixed
          default palette, not stored here -- see c1palette.ksy).
      - id: display_name
        type: mfc_string
        doc: e.g. "Feverfew", "Tomato".
      - id: description
        type: mfc_string
        doc: e.g. "Reduces sleepiness and exhaustion".
  mfc_string:
    doc: >
      1-byte length (0-254) then that many raw bytes. A length byte of
      0xFF is real MFC convention for an escape to a longer length, but
      has never been observed in either real specimen of this format.
    seq:
      - id: length
        type: u1
      - id: text
        type: str
        encoding: ascii
        size: length
