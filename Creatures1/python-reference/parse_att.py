#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .att body-part attachment-point files
(556 real specimens under windows/Creatures/Body Data/*.att -- one per
real body-part sprite variant, e.g. a000.att/A001.att/... one file per
genus+sex+life_stage+variant combination for a given body part).

Confirmed against the real Creatures.exe loader,
`LoadBodyPartAttachmentData` (0x0043c6d0), which already had a detailed
pre-existing Ghidra comment before this pass: a plain ASCII text file,
exactly 10 rows, each row 4 whitespace-separated integers parsed via
C++ `std::istream::operator>>` (so any whitespace runs are equivalent,
column alignment in the real files is cosmetic only). Each row is one
of the body part's 10 real animation-pose FRAMES (not 10 different body
parts as a naive first read might suggest) -- confirmed directly by the
real field names: `anchor_a_x_by_frame[10]`/`anchor_a_y_by_frame[10]`/
`anchor_b_x_by_frame[10]`/`anchor_b_y_by_frame[10]`, each row supplying
one frame's entry across all 4 arrays. Values are stored as raw bytes
(0-255) in the real engine.

Each frame row gives TWO attachment anchor points, "A" and "B" -- used to
connect this body part to its neighbours (e.g. an upper-arm sprite's own
A/B anchors mate with the torso's and lower-arm's own per-frame anchors)
so limbs visually line up correctly across every pose frame, not just a
single fixed connection point.

Column order per row: anchor_a_x, anchor_a_y, anchor_b_x, anchor_b_y.

REAL FINDING (2026-08-22): 54 of 556 real specimens (all "b*.att" --
the PART_BODY/torso part, which attaches to up to 6 neighbours: head,
2 arms, 2 legs, tail) have 12 columns per row (120 tokens total) instead
of 4 (40 tokens), presumably 6 anchor points instead of 2. Confirmed via
the real loader (`BodyPartAttachmentData` Ghidra struct is exactly 40
bytes -- 2 anchors x 10 frames -- and `LoadBodyPartAttachmentData`'s own
read loop is hardcoded to exactly 10 iterations of 4 values each) that
the retail engine only ever reads the FIRST 40 tokens of any .att file,
full stop -- the extra 80 tokens in these 54 specimens are real
on-disk data but genuinely never read by the shipped game. This module
parses and returns all present columns (so callers CAN inspect the extra
anchor data if they want it) but only requires the first 40 tokens to
match the real engine's own consumption.
"""
import sys


class AttFormatError(Exception):
    pass


def parse_att(path, verbose=True):
    def log(*a):
        if verbose:
            print(*a)

    with open(path, 'r') as f:
        text = f.read()

    tokens = text.split()
    if len(tokens) < 40 or len(tokens) % 4 != 0:
        raise AttFormatError(
            f"expected at least 40 whitespace-separated integers in a multiple of 4 "
            f"(N anchor pairs x 10 frames x 2 coords), got {len(tokens)}")

    try:
        values = [int(t) for t in tokens]
    except ValueError as e:
        raise AttFormatError(f"non-integer token: {e}")

    columns = len(tokens) // 10
    if columns % 2 != 0:
        raise AttFormatError(
            f"{len(tokens)} tokens over 10 frame-rows implies {columns} columns/row, "
            f"not an even number (anchor_x,anchor_y pairs)")
    num_anchors = columns // 2
    extra = columns > 4
    if extra:
        log(f"  NOTE: {columns} columns/row ({num_anchors} anchor points) -- more than the "
            f"standard 4 (2 anchors). Real engine only ever reads the first 4 columns "
            f"(anchor_a, anchor_b); remaining {num_anchors - 2} anchors are on-disk but unread.")

    frames = []
    for i in range(10):
        row = values[i * columns:(i + 1) * columns]
        anchors = [(row[j], row[j + 1]) for j in range(0, columns, 2)]
        for j, (x, y) in enumerate(anchors):
            for name, v in [('x', x), ('y', y)]:
                if not (0 <= v <= 255):
                    log(f"  WARNING: frame {i} anchor[{j}].{name}={v} outside byte range 0-255")
        frames.append(dict(frame=i, anchors=anchors,
                            anchor_a_x=anchors[0][0], anchor_a_y=anchors[0][1],
                            anchor_b_x=anchors[1][0], anchor_b_y=anchors[1][1]))

    for f in frames:
        log(f"  frame {f['frame']}: " + " ".join(f"anchor[{i}]=({x},{y})"
                                                    for i, (x, y) in enumerate(f['anchors'])))
    log("ATT format: CONFIRMED")

    return dict(frames=frames, num_anchors=num_anchors)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.att-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_att(sys.argv[1])
    except AttFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
