#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .cob agent files and their .rcb removal
counterparts (identical layout). Mirrors ../c1cob.ksy; see that file's doc
header for the evidence behind each field.

Source: `LoadInjectorCobFile` (0x00408370) in the Community Edition
`Injector.exe` -- an mfc140 rebuild, and the only compiled loader available,
since the retail game never reads these files. Byte-exact against all 24
shipped .COB and 34 shipped .RCB specimens. openc2e
(`src/fileformats/c1cobfile.cpp`) reads the same bytes with a narrower model.

Format (little-endian, no MFC object-tag framing):

    num_records: u16            loader loops on it; openc2e calls it a
                                version and requires 1; every specimen is 1
    records[num_records]:
        quantity_available: u16 0 and >= 255 are unlimited; 1..254 count down
        expiration_month:   u32 \
        expiration_day:     u32  > all zero = never expires
        expiration_year:    u32 /  (a year <= 99 means 1900 + year)
        num_object_scripts:     u16
        num_activation_scripts: u16
        activation_cursor:      u16  openc2e reads this and the next u16 as
        activation_mode:        u16  one u32 "quantity_used"
        object_scripts[num_object_scripts]:         string
        activation_scripts[num_activation_scripts]: string
        picture_width:      u32
        picture_height:     u32
        picture_row_stride: u16 CSprite row stride; equals width in every
                                specimen, 0 in one known community file
        picture_data:       width*height bytes, 8bpp, rows bottom-to-top,
                            indexed into C1's default palette
        name:               string
        description:        string  empty in every specimen -- the single
                                    "trailing NUL" byte earlier models could
                                    not explain

Script roles, from CAgentsPage::InjectSelectedCob (0x00405e60) and
RemoveSelectedCob (0x00406220), and confirmed by logging a live injection:
`object_scripts` run in full each time the record is applied (a .cob's
`scrp f g s e,...` event scripts); `activation_scripts` are the action
itself (a .cob's `inst,new: simp ...,endm`, a .rcb's removal). Mode 0 runs
one activation script per use, walking from the last entry backwards; any
other mode runs them all.

Strings use MFC's CString prefix: a 1-byte length, or 0xFF then a u16 length.
"""
import struct
import sys


class CobFormatError(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def u8(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def bytes_(self, n):
        if self.pos + n > len(self.data):
            raise CobFormatError(f"read of {n} bytes at {self.pos:#x} runs past end of file")
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def mfc_string(self):
        length = self.u8()
        if length == 255:
            length = self.u16()
        return self.bytes_(length).decode('latin1')


ONE_PER_ACTIVATION = 0


def parse_record(r, log):
    quantity_available = r.u16()
    expiration = (r.u32(), r.u32(), r.u32())          # month, day, year
    num_object_scripts = r.u16()
    num_activation_scripts = r.u16()
    activation_cursor = r.u16()
    activation_mode = r.u16()

    object_scripts = [r.mfc_string() for _ in range(num_object_scripts)]
    activation_scripts = [r.mfc_string() for _ in range(num_activation_scripts)]

    picture_width = r.u32()
    picture_height = r.u32()
    picture_row_stride = r.u16()
    picture_data = None
    if picture_width > 0 and picture_height > 0:
        picture_data = r.bytes_(picture_width * picture_height)

    name = r.mfc_string()
    description = r.mfc_string()

    unlimited = quantity_available == 0 or quantity_available >= 255
    log(f"  name={name!r} description={description!r}")
    log(f"  quantity={'unlimited' if unlimited else quantity_available} "
        f"expiration(m/d/y)={expiration[0]}/{expiration[1]}/{expiration[2]}"
        f"{' (never)' if expiration == (0, 0, 0) else ''}")
    log(f"  {len(object_scripts)} object_scripts, {len(activation_scripts)} activation_scripts "
        f"(mode={activation_mode}"
        f"{' one_per_activation' if activation_mode == ONE_PER_ACTIVATION else ' all'}, "
        f"cursor={activation_cursor})")
    for i, s in enumerate(object_scripts):
        if not s.startswith('scrp '):
            log(f"  NOTE: object_scripts[{i}] doesn't start with 'scrp ' -- {s[:30]!r}")
    log(f"  picture {picture_width}x{picture_height}, row_stride={picture_row_stride}"
        f"{'' if picture_row_stride in (picture_width, 0) else ' (UNEXPECTED)'}")

    return dict(
        quantity_available=quantity_available, expiration=expiration,
        activation_cursor=activation_cursor, activation_mode=activation_mode,
        object_scripts=object_scripts, activation_scripts=activation_scripts,
        picture_width=picture_width, picture_height=picture_height,
        picture_row_stride=picture_row_stride, picture_data=picture_data,
        name=name, description=description,
    )


def parse_cob(path, verbose=True):
    data = open(path, 'rb').read()
    r = Reader(data)

    def log(*a):
        if verbose:
            print(*a)

    num_records = r.u16()
    log(f"num_records={num_records}")
    records = []
    for index in range(num_records):
        log(f"record {index}:")
        records.append(parse_record(r, log))

    trailing = len(data) - r.pos
    log(f"parsed to {r.pos:#x} / file size {len(data):#x}, trailing bytes={trailing}")
    log("COB format: CONFIRMED" if trailing == 0 else "COB format: MISMATCH")
    return dict(num_records=num_records, records=records, trailing_bytes=trailing)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.cob-or-.rcb-file>", file=sys.stderr)
        sys.exit(1)
    try:
        result = parse_cob(sys.argv[1])
    except CobFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
    sys.exit(0 if result['trailing_bytes'] == 0 else 1)
