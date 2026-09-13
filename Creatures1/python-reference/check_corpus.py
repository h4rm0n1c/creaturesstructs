#!/usr/bin/env python3
"""Run every parser over a corpus and fail unless each file parses byte-exact.

The point is not that the parsers work today -- it is that a wrong field can
look right for years on the wrong specimens. The `sleep_indicator_object`
regression is the case in point: the parser modelled it as never read and
compensated with a 2-byte prefix, which is byte-for-byte indistinguishable from
the truth whenever the indicator is NULL. Nine .exp specimens agreed, for the
single reason that every creature in them was awake. One world with a sleeping
norn took the whole file out of alignment.

So a corpus is only as good as its coverage of the states that discriminate:

  - a World.sfc holding a LIVE sleep indicator (non-null
    Creature.sleep_indicator_object) -- see the caveat below, this one is
    subtle and is the case that actually bit
  - a World.sfc containing a PREGNANT creature (non-zero child genome)
  - a creature carrying instincts (instinct_count > 0)
  - a world with objects of every class the dispatcher knows

Absence of a failure here means the corpus did not cover the case, not that the
parser is right. Add specimens when a new state is found in the wild.

KNOWN GAP -- the sleep-indicator specimen is NOT in this repo.

An exported creature cannot supply it, however soundly the creature was
sleeping. The indicator is a world object -- the floating "Zzz" -- and export
nulls the reference: a .exp of a sleeping norn carries
skeleton.sleep_indicator_active = 1 but sleep_indicator_object = None. With a
NULL reference the correct model and the old 2-byte-prefix model consume
identical bytes, so such a file passes under both and discriminates nothing.
This was measured, not assumed: a freshly exported sleeping creature parses
clean under the buggy parser.

The discriminating property is therefore not "a creature is asleep" but "a
creature holds a live sleep-indicator object", which only exists inside a
World.sfc. The specimen that exposed the bug is a 1.5 MB personal save and is
not committed here. Until an equivalent world is added, this checker will pass
on the repo's own corpus while blind to exactly the failure it was written for.

Usage:  python3 check_corpus.py <file-or-directory> [...]
Exit:   0 if every file parsed with zero bytes remaining, 1 otherwise.
"""
import io
import contextlib
import pathlib
import sys

import parse_sfc


def check(path: pathlib.Path) -> tuple[bool, str]:
    entry = parse_sfc.parse_exp if path.suffix.lower() == '.exp' else parse_sfc.parse_sfc
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            entry(str(path))
    except Exception as error:                      # noqa: BLE001 - report, don't raise
        tail = buffer.getvalue().strip().splitlines()
        where = tail[-1] if tail else '(no progress)'
        return False, f'{type(error).__name__}: {error} | last: {where}'
    last = buffer.getvalue().strip().splitlines()[-1]
    if 'remaining= 0' not in last:
        return False, f'trailing bytes not consumed | {last}'
    return True, last


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    files: list[pathlib.Path] = []
    for argument in argv[1:]:
        root = pathlib.Path(argument).expanduser()
        if root.is_dir():
            for pattern in ('*.sfc', '*.exp', 'World.sfc'):
                files.extend(sorted(root.rglob(pattern)))
        elif root.is_file():
            files.append(root)
    files = sorted(set(files))
    if not files:
        print('no specimens found')
        return 2

    failures = 0
    for path in files:
        ok, detail = check(path)
        print(f'  {"ok  " if ok else "FAIL"}  {path.name:32} {detail}')
        failures += 0 if ok else 1
    print(f'\n{len(files) - failures}/{len(files)} specimens parsed byte-exact')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
