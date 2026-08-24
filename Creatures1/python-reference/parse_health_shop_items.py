#!/usr/bin/env python3
"""
Structural verifier for the private per-kit "AddObject"/"shop" item-catalog
files `windows/Creatures/Health` (Health Kit.exe, 3 real items) and
`windows/Creatures/Aphro` (Breeders_Kit.exe, 2 real items) -- both files have
no extension. Not the same format as the already-closed `.cob`/`.rcb` format
(no version/quantity_available/expiry/name-trailer fields), and not a
COB-embedded picture either -- a genuinely distinct, private single-purpose
catalog format read by `CAddObjectPage::LoadItemCollection`
(0x004052b0 in Health Kit.exe) via a real `CFile::Open` + `CArchive` wrap.

Format confirmed byte-exact against both real specimens (Health: 3 items,
0 bytes remaining; Aphro: 2 items, 0 bytes remaining), cross-checked
against real compiled code in 3 places: `CShopItem::SerializeHealthSpriteRecord`
(0x00410740, CShopItem's own vtable override of the base
`HealthAudioBase::SerializeSpriteData`, installed by `CShopItem::Constructor`
0x004105f0 via `CShopItemVtable` at 0x004134c8), `HealthAudioBase::
SerializeSpriteData` (0x00408750, its `mode_flags & 1` load/store branch
confirmed to match real MFC `CArchive::Mode` -- store=0, load=1), and
`CSprite::SerializeBitmapData` (0x0040e6c0, byte-exact via raw disassembly:
an 8-byte row_stride+height archive read, then a plain 2-byte width read,
no hidden padding).

REAL TRAP FOUND AND AVOIDED (worth remembering): a naive "scan for a
printable-ASCII run" read of the on-disk bytes strongly suggested
`health_command_string` was NUL-terminated raw text -- it isn't. All three
per-item strings use the ordinary MFC 1-byte length-prefixed CString wire
format (same convention as `tools/parse_cob.py`'s `mfc_string`, no NUL). The
trap: `health_command_string`'s real 1-byte length is 0x5f=95, which is ALSO
the ASCII code for '_' -- the command text's own real first character -- so
a naive scan silently absorbed the length byte as if it were content,
making the string look 2 bytes longer and coincidentally NUL-terminated
(the following sprite header's `row_stride` low byte, 0x20, also renders as
a printable space, compounding the illusion). Always locate a real anchor
string (here: a literal unique substring like "Feverfew") and solve
backwards/forwards from it before trusting a byte-shape guess.

Format (all little-endian):
    item_count: u16
    item_count x item records, each:
        remaining_quantity: u16 (12 in every real item seen across both
                 files -- meaning/use not investigated further; may be an
                 "always available" sentinel rather than a live counter)
        health_command_string: mfc_string (see below) -- the real CAOS
                 install command for this item, e.g. "inst,new: simp herb
                 3 0 3500 0,setv clas 33819136,setv attr 67,bhvr 0 1,setv
                 obv0 1,pose 2,edit" (no leading "_" -- the game
                 presumably prepends the literal INST-block delimiter at
                 use time; it is not itself stored in the file)
        row_stride_bytes: u32
        height: u32
        width: u16
        pixel_data: row_stride_bytes*height raw indexed bytes (this
                 item's dispenser-icon sprite, 8bpp, palette not stored)
        display_name: mfc_string -- e.g. "Feverfew", "Tomato"
        description: mfc_string -- e.g. "Reduces sleepiness and exhaustion"

mfc_string: 1-byte length (0-254) then that many raw bytes. A length byte
of 0xFF (a longer-string escape) is real MFC convention but has never been
observed in either real specimen -- raises NotImplementedError rather than
silently mis-parsing if ever hit.

Real content confirms these are genuine shop/dispenser catalogs: Health
Kit's 3 items are Feverfew/Morning Glory/Cheese (health-boosting herbs and
food); Breeders_Kit's 2 Aphro items are Tomato/Ugly Tomato (fertility-
boosting food, one with an inverted "Reduces sex drive" effect).
"""
import struct
import sys


class HealthShopFormatError(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def u16(self):
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def bytes_(self, n):
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def mfc_string(self):
        length = self.data[self.pos]
        self.pos += 1
        if length == 0xff:
            raise NotImplementedError(
                "0xFF long-string escape never observed in a real specimen -- "
                "not implemented rather than guessed at")
        return self.bytes_(length).decode('latin1')


def parse_health_shop_items(path, verbose=True):
    data = open(path, 'rb').read()
    r = Reader(data)

    def log(*a):
        if verbose:
            print(*a)

    item_count = r.u16()
    log(f"item_count={item_count}")

    items = []
    for i in range(item_count):
        remaining_quantity = r.u16()
        health_command_string = r.mfc_string()
        row_stride_bytes = r.u32()
        height = r.u32()
        width = r.u16()
        n = row_stride_bytes * height
        if r.pos + n > len(data):
            raise HealthShopFormatError(
                f"item {i}: pixel data ({n} bytes) runs past EOF at {hex(r.pos)}")
        pixel_data = r.bytes_(n)
        display_name = r.mfc_string()
        description = r.mfc_string()

        log(f"  [{i}] qty={remaining_quantity} cmd={health_command_string!r}")
        log(f"       sprite={width}x{height} (row_stride={row_stride_bytes}) "
            f"name={display_name!r} desc={description!r}")

        items.append(dict(
            remaining_quantity=remaining_quantity,
            health_command_string=health_command_string,
            row_stride_bytes=row_stride_bytes, height=height, width=width,
            pixel_data=pixel_data, display_name=display_name, description=description,
        ))

    trailing = len(data) - r.pos
    log(f"parsed {len(items)} items, pos={hex(r.pos)} / filesize={hex(len(data))}, "
        f"trailing={trailing} bytes")
    ok = trailing == 0
    log("HEALTH SHOP ITEM format: CONFIRMED" if ok else "HEALTH SHOP ITEM format: MISMATCH")

    return dict(item_count=item_count, items=items, trailing_bytes=trailing)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-Health-or-Aphro-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_health_shop_items(sys.argv[1])
    except (HealthShopFormatError, NotImplementedError) as e:
        print("STOPPED:", e)
        sys.exit(1)
