meta:
  id: c1gno
  title: Creatures 1 gene notes catalog (.GNO)
  application: Creatures 1 (development tooling)
  file-extension: gno
  endian: le
  license: CC0-1.0
doc: |
  A `.GNO` file is a completely different, unrelated format from a `.gen`
  genome (see `c1gen.ksy`) despite the similar name and shared
  `Genetics/` directory -- a flat catalog attaching a human-readable label
  and an optional free-text RTF design note to every gene in one canonical
  genome (the two real specimens shipped with the game are
  `Genetics/NORN.GNO` and `Genetics/Grendel.GNO`).

  IMPORTANT PROVENANCE NOTE, unlike this project's other closed C1
  formats: no shipped C1 executable references the `.gno` extension at
  all (checked via a `strings` sweep across every `.exe` under
  `windows/Creatures/` -- zero hits). This is almost certainly a genuine
  CyberLife-internal development/authoring artifact, produced by an
  internal gene-editing tool to document the canonical Norn/Grendel
  genomes during development, and never consumed by any retail binary --
  so unlike every other spec in this repo, there is no compiled-code
  ground truth to check this layout against. It was recovered purely from
  the real file bytes, confirmed by decoding both real specimens to a
  clean, exact end-of-file with every byte accounted for.

  The genes it documents ARE real, retail C1 genes -- `family`/`subtype`
  in each record match the real gene-type byte values from `c1gen.ksy`
  exactly wherever cross-checked (e.g. `family=2, subtype=2` on every
  "- Appearance" labelled record). Some records carry genuine original
  CyberLife engineering commentary not found in any other surviving
  source, e.g. (from `NORN.GNO`) a description on the "Oestral cycle (F)
  - Receptor" record explaining the fertility-cycle emitter/receptor
  thermostat design, with an inline note on the matching Emitter record
  referencing the original C++ source's `OVULATEON`/`OVULATEOFF`
  constants by name.
seq:
  - id: version
    type: u2
    doc: Observed as 2 in both real specimens.
  - id: num_records
    type: u2
  - id: records
    type: gno_record
    repeat: expr
    repeat-expr: num_records
types:
  gno_record:
    seq:
      - id: family
        type: u2
        doc: Matches the real C1 gene family byte (see c1gen.ksy) exactly.
      - id: subtype
        type: u2
        doc: Matches the real C1 gene subtype byte (see c1gen.ksy) exactly.
      - id: sequence_in_type
        type: u2
        doc: >
          1-based position among genes of this same family+subtype, in
          this catalog's own canonical order (e.g. "001 Head", "002 Body",
          "003 Legs", "004 Arms" for the 4 real Appearance-gene body-part
          groups).
      - id: reserved
        type: u2
        doc: Observed as 0 in every record checked; meaning not established.
      - id: len_label
        type: u2
      - id: label
        type: str
        encoding: ascii
        size: len_label
      - id: len_description
        type: u2
        doc: 0 when no design note was ever authored for this gene (the common case).
      - id: description
        type: str
        encoding: ascii
        size: len_description
        if: len_description > 0
        doc: Real Windows RTF markup (starts literally "{\rtf1\ansi...") when present.
