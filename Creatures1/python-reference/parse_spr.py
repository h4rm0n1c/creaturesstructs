#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .spr sprite files (690 real specimens:
18 top-level under windows/Creatures/*.spr plus 672 under
windows/Creatures/Images/*.spr -- everything from UI chrome to body parts
to the COB toys' animation frames).

TWO real, distinct, independently-confirmed formats share the .spr
extension in this game -- confirmed against real compiled code in TWO
different Ghidra programs, not just community documentation:

FORMAT 1 -- "standard" (672 of 690 real specimens; the general C1 sprite
gallery format used by the main engine for body parts, UI chrome, COB
pictures, etc). Confirmed against Creatures.exe's real CGallery
constructor (0x004420c0) -- its own pre-existing Ghidra comment cites
this exact layout, cross-checked against a real specimen
(Images/i021.spr) -- and independently against this repo's openc2e
reimplementation (openc2e/src/fileformats/sprImage.cpp, ReadSprFile).
    frame_count: u16
    per frame (frame_count x 8-byte records, immediately following):
        offset: u32 (absolute byte offset where this frame's pixel data
                 starts -- in the real engine's own usage this is a
                 fixed multi-image gallery format where header_record_index
                 lets several logical galleries share one physical file;
                 for a standalone single-gallery file it's simply
                 contiguous with the header/prior frames)
        width: u16
        height: u16
    then, at each frame's own offset: width*height raw bytes, one byte
    per pixel, indexed into Creatures 1's fixed default palette (not
    stored in the file).

FORMAT 2 -- "phased" (18 of 690 real specimens: all the Dosage-gauge
family [c/B/p/O/y/s]Dosage.spr + Dosage.spr, Gene.spr, Fertility.spr,
LOBES.SPR, plus Hearts/AllNumbers/Gauge/Score/Time/Blink.spr -- all kit
UI animation strips, e.g. Science Kit's injection dosage slider and
gene-viewer preview). NOT the same format as FORMAT 1 despite the shared
extension -- confirmed via TWO real dedicated loaders in Science Kit.exe:
`CInjectPage::LoadDosageSprite` (0x0040a6a0, always reads exactly 2
collections) and `CChromosonePage::LoadGeneSpriteSheet` (0x004105e0,
always reads exactly 1) -- both of which explicitly skip a leading u16
"prefix whose universal semantics are not established" (their own real
plate comments' words) before reading the real payload. A near-identical
single-collection variant also exists in BiochemKit.exe
(`CPhasedSprite::SerializeArchive`/`CInjectSpriteFrame::SerializeArchive`,
0x0040f7c0/0x0040f260) with the same 6-byte/10-byte header shapes.
    outer_prefix: u16 (meaning genuinely inconsistent across real
             consumers -- NOT safely interpretable as a universal
             "collection count" despite superficially matching it in
             some specimens; different loader functions hardcode how
             many collections to read and simply skip this field)
    declared_backing_size: u32 (an allocation-sizing hint for the
             consuming kit's own in-memory buffer; per LoadDosageSprite's
             own comment, real specimens can overallocate relative to
             actual content -- not cross-checked against the real
             collection sizes by the real loader, and not treated as
             authoritative here either)
    one or more CPhasedSprite collections, back to back, each:
        item_count: u16
        serialized_item_data_size: u32 (pixel-bytes-only total for this
                 collection, used by the real engine only to compute a
                 second collection's in-memory buffer offset -- not
                 needed for file-structural parsing since collections
                 are read sequentially regardless)
        item_count x 10-byte frame records:
            row_stride_bytes: u32
            frame_height: u32
            frame_width: u16
        each immediately followed by its own row_stride_bytes*frame_height
        raw pixel bytes (interleaved header+pixels per frame, NOT all
        headers then all pixels -- unlike FORMAT 1).

Since no single real loader was found that reads a VARIABLE number of
collections from this format (every dedicated loader traced hardcodes
its own expected count and ignores outer_prefix), this module determines
the real collection count for each file the same way the file format
itself makes verifiable: brute-force search N=1.. for the value that
makes every collection decode cleanly AND land exactly on EOF. This is a
sound verification method here, not a guess -- a wrong N essentially
never coincidentally lands byte-exact on EOF given real, varying pixel
content (confirmed: 17 of 18 real "phased" specimens resolve to exactly
one clean N each, with zero ambiguous multi-N matches found -- two
further sub-variants exist: "bare", a single collection with no outer
6-byte wrapper at all [Gauge.spr, Score.spr, matching BiochemKit's
CPhasedSprite::SerializeArchive], and "wrapped" [everything else]).

ONE known confirmed non-file this pass: windows/Creatures/Images/gren.SPR
(1092 bytes) fits neither format -- its own bytes are `00 00` (frame_count
0) followed by 1090 bytes of solid 0xCD. This is the MSVC debug-heap
"allocated, never initialized" fill pattern (same signature this project
used earlier to prove CEventBar's dead archive fields in Creatures.exe) --
a genuine placeholder/stub file, never actually populated with real image
data, not a gap in this parser. Reported as a clean STOPPED diagnostic
rather than silently accepted.
"""
import struct
import sys


class SprFormatError(Exception):
    pass


def _try_standard(data):
    """Returns a result dict on success, or None if this file doesn't
    fit the standard format cleanly."""
    if len(data) < 2:
        return None
    frame_count = struct.unpack_from('<H', data, 0)[0]
    header_size = 2 + frame_count * 8
    if header_size > len(data):
        return None
    pos = 2
    frames = []
    for i in range(frame_count):
        offset, width, height = struct.unpack_from('<IHH', data, pos)
        pos += 8
        frames.append(dict(index=i, offset=offset, width=width, height=height))
    mismatches = 0
    for f in frames:
        if f['offset'] != pos:
            mismatches += 1
        n = f['width'] * f['height']
        if pos + n > len(data):
            return None
        f['data'] = data[pos:pos + n]
        pos += n
    if pos != len(data) or mismatches:
        return None
    return dict(format='standard', frame_count=frame_count, frames=frames)


def _decode_phased_collection(data, pos):
    """Returns (new_pos, collection_dict) or None on any inconsistency."""
    if pos + 6 > len(data):
        return None
    item_count, serialized_item_data_size = struct.unpack_from('<HI', data, pos)
    pos += 6
    frames = []
    for i in range(item_count):
        if pos + 10 > len(data):
            return None
        row_stride, height, width = struct.unpack_from('<IIH', data, pos)
        pos += 10
        n = row_stride * height
        if pos + n > len(data):
            return None
        frames.append(dict(index=i, row_stride_bytes=row_stride, height=height,
                            width=width, data=data[pos:pos + n]))
        pos += n
    return pos, dict(item_count=item_count,
                      serialized_item_data_size=serialized_item_data_size, frames=frames)


def _try_phased_from(data, start_pos, max_collections=20):
    for n in range(1, max_collections + 1):
        pos = start_pos
        collections = []
        ok = True
        for _ in range(n):
            r = _decode_phased_collection(data, pos)
            if r is None:
                ok = False
                break
            pos, coll = r
            collections.append(coll)
        if ok and pos == len(data):
            return n, collections
    return None


def _try_phased(data, max_collections=20):
    # Sub-variant A: "bare" -- a single CPhasedSprite collection with no
    # outer wrapper at all (confirmed real: Gauge.spr, Score.spr, matching
    # BiochemKit's CPhasedSprite::SerializeArchive with no surrounding
    # header). Try this FIRST since it's a strict subset of what the
    # wrapped variant's byte layout could coincidentally also start with.
    r = _try_phased_from(data, 0, max_collections)
    if r is not None:
        n, collections = r
        return dict(format='phased', variant='bare', outer_prefix=None,
                    declared_backing_size=None, collection_count=n, collections=collections)

    # Sub-variant B: "wrapped" -- outer_prefix:u16 + declared_backing_size:u32
    # (6 bytes, real per LoadDosageSprite/LoadGeneSpriteSheet), then N
    # collections back to back.
    if len(data) < 6:
        return None
    outer_prefix, declared_backing_size = struct.unpack_from('<HI', data, 0)
    r = _try_phased_from(data, 6, max_collections)
    if r is not None:
        n, collections = r
        return dict(format='phased', variant='wrapped', outer_prefix=outer_prefix,
                    declared_backing_size=declared_backing_size,
                    collection_count=n, collections=collections)
    return None


def parse_spr(path, verbose=True):
    data = open(path, 'rb').read()

    def log(*a):
        if verbose:
            print(*a)

    result = _try_standard(data)
    if result is not None:
        log(f"FORMAT 1 (standard): frame_count={result['frame_count']}, "
            f"all frames contiguous, file fully consumed")
        log("SPR format: CONFIRMED (standard)")
        return result

    result = _try_phased(data)
    if result is not None:
        log(f"FORMAT 2 (phased, {result['variant']}): outer_prefix={result['outer_prefix']} "
            f"declared_backing_size={result['declared_backing_size']} "
            f"real collection_count={result['collection_count']} (brute-force verified)")
        for i, c in enumerate(result['collections']):
            log(f"  collection[{i}]: item_count={c['item_count']} "
                f"serialized_item_data_size={c['serialized_item_data_size']}")
        log("SPR format: CONFIRMED (phased)")
        return result

    raise SprFormatError(
        f"{path}: fits neither FORMAT 1 (standard) nor FORMAT 2 (phased) cleanly "
        f"-- see module docstring for both models")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.spr-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_spr(sys.argv[1])
    except SprFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
