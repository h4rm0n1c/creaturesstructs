#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .gno "gene notes" catalog files (the 2
real specimens shipping under windows/Creatures/Genetics/{NORN,Grendel}.GNO).

IMPORTANT PROVENANCE NOTE, unlike every other format closed this session:
no shipped C1 executable references the ".gno" extension at all (checked
via `strings` across every .exe in windows/Creatures/, zero hits). This is
a genuine internal CyberLife development/authoring artifact -- almost
certainly used by an internal gene-editing tool during development to
attach human-readable names and free-text (RTF) design notes to every
real gene in the canonical Norn/Grendel genome, never consumed by any
retail binary. There is no real compiled-code ground truth to verify this
format against, unlike every other format this session -- this module's
layout was reverse-engineered purely from the real file bytes, confirmed
by decoding both real specimens to a clean, exact end-of-file with every
byte accounted for (not a heuristic/approximate match).

Format (all little-endian):
    version: u16 (2 in both real specimens)
    record_count: u16 (323 for NORN.GNO, matches the real parsed count
             exactly; a genuine file-level record count, not a per-record
             field -- an earlier draft of this module misread the file's
             first record as having an anomalous "extra" field before
             realizing this was actually the real file header)
    then exactly record_count records, each:
        family: u16 (matches the real C1 gene family byte from
                 tools/parse_gene.py's GENE_BODY_SIZES exactly wherever
                 checked, e.g. family=2 for every "- Appearance"/
                 "- Genus"/etc. CREATURE-family label seen)
        subtype: u16 (matches the real C1 gene subtype byte exactly,
                 e.g. subtype=2 for every "- Appearance" label -- one
                 curiosity: record 0 in both real specimens has
                 family=2/subtype=1 [Genus gene] despite its label
                 "001 Header - compulsory" reading like a meta-record,
                 not investigated further since it parses cleanly either
                 way)
        sequence_in_type: u16 (1-based position among genes of this same
                 family+subtype, in the catalog's own canonical order --
                 e.g. "001 Head"/"002 Body"/"003 Legs"/"004 Arms" for the
                 4 real Appearance-gene body-part groups)
        reserved: u16 (0 in every record checked; meaning not established)
        label_length: u16
        label: label_length bytes (ASCII, e.g. "001 Head - Appearance ")
        description_length: u16 (0 when no design note was ever authored
                 for this gene -- the common case; a real length when one
                 was)
        description: description_length bytes of real Windows RTF markup
                 (starting literally "{\\rtf1\\ansi...") when
                 description_length > 0.

Real per-gene design notes recovered this way include genuine CyberLife
engineering detail not found in ANY other source this project has used,
e.g. record "020 Oestral cycle (F) - Receptor" in NORN.GNO: "Controls
fertility cycle in females - they become fertile if oestrogen levels are
high... The cycle is controlled by an emitter which produces oestrogen
only when the creature is NOT fertile, thus producing a thermostat
effect." -- and "(Note: OVULATEON & OVULATEOFF constants in code
detemine the hysteresis thresholds of this emitter locus)" on the
matching Emitter record -- literal original developer commentary
referencing their own C++ source symbol names.
"""
import struct
import sys


class GnoFormatError(Exception):
    pass


def parse_gno(path, verbose=True):
    data = open(path, 'rb').read()

    def log(*a):
        if verbose:
            print(*a)

    if len(data) < 4:
        raise GnoFormatError(f"file too short ({len(data)} bytes)")

    version, record_count = struct.unpack_from('<HH', data, 0)
    pos = 4
    log(f"version={version} record_count={record_count}")

    records = []
    for index in range(record_count):
        if pos + 10 > len(data):
            raise GnoFormatError(f"record {index} header runs past EOF at {hex(pos)}")
        family, subtype, sequence_in_type, reserved, label_length = \
            struct.unpack_from('<5H', data, pos)
        pos += 10
        if pos + label_length > len(data):
            raise GnoFormatError(f"record {index} label runs past EOF at {hex(pos)}")
        label = data[pos:pos + label_length].decode('latin1')
        pos += label_length

        if pos + 2 > len(data):
            raise GnoFormatError(f"record {index} description_length runs past EOF at {hex(pos)}")
        description_length = struct.unpack_from('<H', data, pos)[0]
        pos += 2
        description = None
        if description_length:
            if pos + description_length > len(data):
                raise GnoFormatError(f"record {index} description runs past EOF at {hex(pos)}")
            description = data[pos:pos + description_length].decode('latin1')
            pos += description_length

        records.append(dict(index=index, family=family, subtype=subtype,
                             sequence_in_type=sequence_in_type, reserved=reserved,
                             label=label, description=description))

    trailing = data[pos:]
    trailing_len = len(trailing)
    is_zero_padding = trailing == b'\x00' * trailing_len
    log(f"parsed {len(records)} records, "
        f"{sum(1 for r in records if r['description'])} with an RTF description, "
        f"ends at {hex(pos)} / file size {hex(len(data))}, "
        f"trailing={trailing_len} bytes ({'all zero -- confirmed reserved padding' if is_zero_padding else 'NON-ZERO'})")
    ok = trailing_len == 0 or is_zero_padding
    log("GNO format: CONFIRMED" if ok else "GNO format: MISMATCH (non-zero trailing bytes)")

    return dict(version=version, record_count=record_count, records=records,
                trailing_padding_bytes=trailing_len)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.gno-file>", file=sys.stderr)
        sys.exit(1)
    try:
        result = parse_gno(sys.argv[1])
    except GnoFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
    for r in result['records'][:20]:
        print(f"  [{r['index']:3d}] family={r['family']} subtype={r['subtype']} "
              f"seq={r['sequence_in_type']} {r['label']!r}"
              f"{' (+description)' if r['description'] else ''}")
