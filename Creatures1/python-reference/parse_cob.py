#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .cob agent/object files (the 24 real
specimens shipping under windows/Creatures/*.COB -- toys, gadgets, food,
seasonal decorations).

ALSO HANDLES .rcb (removal COB) FILES UNCHANGED (confirmed 2026-08-22):
these are structurally IDENTICAL to .cob -- Injector.exe's real .rcb
loader (CAgentsPage::RemoveSelectedCob 0x00406220 in Injector.exe) calls
the exact same LoadInjectorCobFile function used for .cob, no separate
format. Verified byte-exact against all 34 real .rcb specimens in
windows/Creatures/*.RCB with zero code changes. Real .rcb conventions:
picture is always 0x0 (no display sprite -- never shown as an
installable object), `name` is typically "unknown" (unused),
`install_scripts` is typically empty, and `removal_scripts` holds the
real uninstall CAOS command(s) that get executed when a user removes the
paired .cob's object from the world (install_scripts, if any, run
first, same order/semantics as a normal .cob).

Format sourced from this repo's own openc2e reimplementation
(openc2e/src/fileformats/c1cobfile.cpp/.h), a mature, independently
community-maintained C1/C2/C3 engine -- NOT from blind guessing. Verified
2026-08-22 by manually decoding two real files byte-for-byte against this
exact layout (Honey Jars.COB, Bed Time Bear.COB) before trusting it, same
methodology used earlier this session for the community Kaitai .exp spec
and the wiki's GEN_files doc: cross-check community documentation against
real data (and, where locatable, real compiled code) before relying on it.

CORRECTION 2026-08-22 (found and fixed same day it was first written): an
earlier draft of this module claimed `Injector.exe`'s LoadInjectorCobFile
(0x00408370) was a private cache format, distinct from the real file
format below. That was wrong -- confirmed by tracing its only caller,
ReloadCobFiles (0x00402bc0), which scans <cob_search_directory>\*.cob via
CFileFind and calls LoadInjectorCobFile directly on each real match, no
conversion step. LoadInjectorCobFile really does read this exact format,
field-for-field, offsets 0-19 matching openc2e's model exactly -- AND it
reveals two things openc2e's implementation doesn't capture, both now
reflected below: (1) the `quantity_used`-sized u32 at offset 20 is
actually real compiled code reading it as two u16 sub-fields, and (2) the
two script arrays' real BEHAVIORAL roles (which openc2e's field names
don't convey) are the reverse of what plain reading of "object_scripts"/
"install_scripts" suggests -- see below.

Format (all little-endian, no MFC object-tag framing):
    version: u16 (only version 1 seen/supported; C1's .cob format has no
             version 2 -- that's C2's separate, incompatible format)
    quantity_available: u16 (vending-machine-style stock limit; 0xffff /
             large values typically mean unlimited in practice)
    expiration_month: u32
    expiration_day: u32
    expiration_year: u32
    num_object_scripts: u16
    num_install_scripts: u16
    next_removal_script_index: u16 (real name/split confirmed via
             Injector.exe's compiled LoadInjectorCobFile -- openc2e reads
             this same 4-byte region as one u32 "quantity_used" instead;
             can't fully disambiguate from data alone since all 24 real
             specimens are zero here, but the compiled engine's own
             interpretation is stronger evidence than an untested guess)
    script_execution_mode: u16 (see above -- a real enum in Injector.exe,
             ONE_REMOVAL_SCRIPT_PER_ACTIVATION is a confirmed member)
    object_scripts: num_object_scripts x length-prefixed string (below).
             REAL ROLE (confirmed via Injector.exe's CCobObject/
             InjectSelectedCob 0x00405e60): these become "install_scripts"
             -- run ONCE, the moment the object is installed into the
             world. Each one starts with a "scrp family genus species
             event" classifier declaration (confirmed by inspection of
             all 24 real specimens) -- these ARE per-classifier event
             handlers, installed once and then triggered by the game's
             event dispatcher for the object's lifetime.
    install_scripts: num_install_scripts x length-prefixed string. REAL
             ROLE (also from Injector.exe): despite the file-field name,
             these become "removal_scripts" -- a ROTATING set of scripts,
             ONE run per activation/removal, advancing
             next_removal_script_index each time (mode-dependent, see
             script_execution_mode). This is the opposite of what the
             field name "install_scripts" suggests taken alone.
    picture_width: u32
    picture_height: u32
    unknown_always_picture_width: u16 (per openc2e: matches picture_width
             in every real specimen seen, or 0 in at least one known
             community specimen -- kept raw here, not asserted)
    picture_data: picture_width*height bytes, ONE row at a time, but
             rows are stored BOTTOM-TO-TOP (row 0 in the byte stream is
             the image's LAST scanline) -- a classic bottom-up-DIB
             convention. 8bpp, indexed into C1's fixed default palette
             (not stored in the file).
    name: length-prefixed string (the object's real in-game name --
             what's shown in the Objects toolbar)
    trailing_nul: 1 byte, always exactly 0x00 -- a REAL on-disk NUL
             terminator after `name`, not just an in-memory convenience.
             Not part of openc2e's c1cobfile.cpp (which doesn't check for
             it and would silently ignore it), but present as the very
             last byte of all 24 real specimens in this repo, zero
             exceptions -- found by this project 2026-08-22 via a clean
             "trailing bytes" mismatch signal across every real
             specimen, exactly 1 byte every time.

Length-prefixed string: 1-byte length; if that byte is 0xFF (255), an
additional u16 gives the real length (MFC's own CArchive CString
serialization convention -- these fields are read via the same helper
whether or not the surrounding code goes through CArchive's higher-level
polymorphic object-tag system).

Every real specimen in this repo has num_object_scripts/num_install_scripts
small (0-20ish) and object_scripts[0] always starts with a literal "scrp "
CAOS classifier declaration (confirmed by inspection).
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
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def mfc_string(self):
        length = self.u8()
        if length == 255:
            length = self.u16()
        return self.bytes_(length).decode('latin1')


def parse_cob(path, verbose=True):
    data = open(path, 'rb').read()
    r = Reader(data)

    def log(*a):
        if verbose:
            print(*a)

    version = r.u16()
    if version != 1:
        raise CobFormatError(f"unsupported .cob version {version} (only version 1 is real C1 format)")

    quantity_available = r.u16()
    expiration_month = r.u32()
    expiration_day = r.u32()
    expiration_year = r.u32()
    log(f"version={version} quantity_available={quantity_available} "
        f"expiration={expiration_month}/{expiration_day}/{expiration_year}")

    num_object_scripts = r.u16()
    num_install_scripts = r.u16()
    # Real compiled-code interpretation (Injector.exe LoadInjectorCobFile),
    # not openc2e's single-u32 "quantity_used" guess -- see module docstring.
    next_removal_script_index = r.u16()
    script_execution_mode = r.u16()
    log(f"num_object_scripts={num_object_scripts} num_install_scripts={num_install_scripts} "
        f"next_removal_script_index={next_removal_script_index} "
        f"script_execution_mode={script_execution_mode}")

    # REAL ROLES (confirmed via Injector.exe, not just file-field names --
    # see module docstring): object_scripts -> run-once install scripts;
    # install_scripts -> rotating removal scripts, one per activation.
    install_scripts = [r.mfc_string() for _ in range(num_object_scripts)]
    removal_scripts = [r.mfc_string() for _ in range(num_install_scripts)]

    for i, s in enumerate(install_scripts):
        if not s.startswith('scrp '):
            log(f"  WARNING: install_scripts[{i}] doesn't start with 'scrp ' -- {s[:30]!r}")
    log(f"read {len(install_scripts)} install_scripts (run once), "
        f"{len(removal_scripts)} removal_scripts (rotated, one per activation)")

    picture_width = r.u32()
    picture_height = r.u32()
    unknown_always_picture_width = r.u16()
    log(f"picture: {picture_width}x{picture_height}, trailing u16={unknown_always_picture_width} "
        f"({'matches width' if unknown_always_picture_width == picture_width else 'DOES NOT MATCH WIDTH'})")

    picture_data = None
    if picture_width > 0 and picture_height > 0:
        picture_data = r.bytes_(picture_width * picture_height)
        log(f"read {len(picture_data)} bytes of picture data (bottom-up 8bpp rows)")

    name = r.mfc_string()
    log(f"name={name!r}")

    trailing_nul = r.u8()
    if trailing_nul != 0:
        log(f"  WARNING: expected trailing NUL byte, got {trailing_nul:#x}")

    trailing = len(data) - r.pos
    log(f"parsed to {hex(r.pos)} / file size {hex(len(data))}, trailing bytes={trailing}")
    if trailing != 0:
        log("  WARNING: extra trailing bytes beyond the expected NUL terminator")

    ok = trailing == 0 and trailing_nul == 0
    log("COB format: CONFIRMED" if ok else "COB format: MISMATCH")

    return dict(
        version=version, quantity_available=quantity_available,
        next_removal_script_index=next_removal_script_index,
        script_execution_mode=script_execution_mode,
        expiration=(expiration_month, expiration_day, expiration_year),
        install_scripts=install_scripts, removal_scripts=removal_scripts,
        picture_width=picture_width, picture_height=picture_height,
        picture_data=picture_data, name=name, trailing_bytes=trailing,
    )


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.cob-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_cob(sys.argv[1])
    except CobFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
