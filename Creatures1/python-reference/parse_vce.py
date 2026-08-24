#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 standalone .vce voice files (the 3
real specimens shipping under windows/Creatures/{male,female,grendel}.vce).

Format confirmed 2026-08-22 two independent ways: (1) cross-checked
against openc2e's own reimplementation (openc2e/src/openc2e/VoiceData.cpp/
.h), which also documents the real speech-synthesis algorithm this data
feeds; (2) confirmed against the REAL compiled loader, Voice::LoadVoiceFile
(0x004454e0 in Creatures.exe) via raw disassembly -- the decompile text
for this function is unreliable (contains a genuine decompiler artifact,
see the Ghidra post-comment on that address) so disassembly was required,
not optional.

Format (580 bytes total, all little-endian, no MFC/CArchive framing at
all -- a plain flat CFile::Read of raw fixed-size records):
    sounds: 32 x (sound_id: char[4], sound_duration: u32) = 256 bytes.
        sound_id is blank (all zero bytes) for slots 0-3 in every real
        specimen -- those are "between words" delay-only slots per
        openc2e's algorithm documentation, matching C1VoiceSoundArchiveRecord.
    trigram_selection_masks: 3 x 27 u32 bit-mask entries = 324 bytes
        (26 letters + 1 "blank"/space, x3 letter-position tables), matching
        C1VoiceTrigramSelectionMask[81].

IMPORTANT: this is the OPPOSITE field order from the SAME 580-byte
payload as archived inside a `.exp` file's embedded Creature record
(Voice::Serialize, 0x00445600, masks-first) -- confirmed via disassembly
of both functions, a real and independent divergence between the two
Voice file formats, not a bug in either. See the existing
C1VoiceArchiveRecord Ghidra struct (masks-first, for .exp) vs this
module / the new C1VoiceFileFormat Ghidra struct (sounds-first, for
standalone .vce).

TRAILING DATA: all 3 real specimens are exactly 640 bytes -- 60 bytes
LARGER than this format (and larger than what LoadVoiceFile ever reads,
confirmed via disassembly: the loader's own cleanup happens immediately
after byte 580). The trailing 60 bytes are BYTE-IDENTICAL across all 3
independently-authored files (male/female/grendel) -- too consistent to
be per-file leftover heap noise, so genuinely real fixed data, but its
purpose is not established this pass (not text, no recognizable
structure) and it is confirmed NOT read by the retail engine at all.
Likely a fixed artifact of whatever internal authoring tool wrote these
files. Exposed here as `trailing_data` for anyone who wants to dig
further, not decoded.

The speech-synthesis ALGORITHM these 580 bytes feed (how English text
gets turned into a sequence of syllable sound files) is documented in
openc2e's VoiceData.cpp (NextSyllableFor) -- not reimplemented here since
this module's job is structural verification of the file, not runtime
speech synthesis.
"""
import struct
import sys


class VceFormatError(Exception):
    pass


def parse_vce(path, verbose=True):
    data = open(path, 'rb').read()

    def log(*a):
        if verbose:
            print(*a)

    if len(data) < 580:
        raise VceFormatError(f"file too short ({len(data)} bytes, need at least 580)")

    pos = 0
    sounds = []
    for i in range(32):
        name = data[pos:pos + 4]
        duration = struct.unpack_from('<I', data, pos + 4)[0]
        pos += 8
        label = name.decode('ascii', 'replace') if name[0] else None
        sounds.append(dict(index=i, sound_id=label, duration=duration))

    log(f"read 32 sound records, pos={hex(pos)}")
    for s in sounds:
        if s['sound_id'] is not None:
            log(f"  [{s['index']:2d}] {s['sound_id']!r} duration={s['duration']}")
        else:
            log(f"  [{s['index']:2d}] (blank -- between-word delay slot) duration={s['duration']}")

    lookup_table = []
    for i in range(81):
        v = struct.unpack_from('<I', data, pos)[0]
        lookup_table.append(v)
        pos += 4
    log(f"read 81 trigram_selection_masks (3 letter-position tables x 27 entries), pos={hex(pos)}")

    assert pos == 580, pos
    trailing_data = data[580:]
    log(f"trailing_data: {len(trailing_data)} bytes (not read by the real engine loader)")

    ok = len(trailing_data) == 60
    log("VCE format: CONFIRMED (580-byte payload matches exactly, "
        "60-byte trailing region present as expected)" if ok else
        f"VCE format: unexpected trailing size {len(trailing_data)} (expected 60)")

    return dict(sounds=sounds, lookup_table=lookup_table, trailing_data=trailing_data)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.vce-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_vce(sys.argv[1])
    except VceFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
