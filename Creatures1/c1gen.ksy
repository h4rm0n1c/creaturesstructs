meta:
  id: c1gen
  title: Creatures 1 genome (.gen / .GNO, and the embedded CGenome payload)
  application: Creatures 1
  file-extension: gen
  endian: le
  license: CC0-1.0
doc: |
  A Creatures 1 genome is a flat sequence of variable-type "gene" records,
  each starting with a 4-byte "gene" tag, terminated by a bare 4-byte
  "gend" tag with no trailing header or body. C1 uses "version 1" of this
  format: there is no `dna2`/`dna3` file-level header the way later
  Creatures games have -- the file (or, for a `.exp`'s embedded genome, the
  payload) starts directly with the first gene's own "gene" tag.

  This is the exact same format for a standalone `.gen` file on disk and
  for the payload bytes inside a `.exp`'s `CGenome` object (see
  `c1exp.ksy`'s `genome` type) -- `CGenome::Serialize` on the `.exp` side
  just wraps this same byte stream with a 9-byte archive prefix
  (payload size, source filename, gender, life stage) and a length, then
  memcpy's this exact stream in as its payload. `.gen` files in this
  project's specimens are padded to a fixed allocation size with trailing
  zero bytes after the real "gend" terminator -- that padding is expected
  and is not part of this spec.

  NOTE: the similarly-named `.GNO` extension (`Genetics/NORN.GNO`,
  `Genetics/Grendel.GNO`) is a **completely different, unrelated format**
  -- a CyberLife-internal gene-notes catalog, not a genome -- see the
  separate `c1gno.ksy` spec.

  Confirmed 2026-08-22 by cross-referencing creatures.wiki's community
  GEN_files documentation against the REAL compiled game code (a live
  Ghidra decompilation of `Creatures.exe`'s own gene loaders --
  `CLobe::LoadGenome` 0x004025d0, `CLobeConnectionRule::LoadFromGenome`
  0x004023a0, `CLobeRuleExpression::LoadFromGenome` 0x00402250,
  `CBiochemistry::LoadGenome` 0x0042e940, `Creature::LoadGenome`
  0x00408960, `CGenome::FindNextMatchingGene` 0x00419040), not taken from
  the wiki alone -- and tested end-to-end against 14 real specimens
  (`Genetics/NORN.GNO`, `Genetics/Grendel.GNO`, several `mum*.gen`/
  `dad*.gen` templates, and the genome payload inside every `.exp` in this
  repo). One real correction versus the community reference: an "Organ"
  gene type (family 3) that page's own table itself labels "Versions 2-3"
  does not exist in real C1 -- no such loader exists anywhere in the
  executable, and family byte 3 never appears in any real C1 specimen
  tested (it would, if it ever did appear, silently fold into family 0
  "brain" under `CGenome::FindNextMatchingGene`'s own `family %= 3`
  normalization whenever family exceeds 2 -- i.e. C1 itself has no notion
  of a distinct family-3 gene type at all).

  Family/subtype pairs not implemented below are not yet confirmed present
  in any real C1 genome; this spec has no generic "unknown gene" recovery
  path (unlike this project's own Python reference parser, which falls
  back to scanning forward for the next gene/gend tag) -- an truly
  unrecognized gene would need a new `cases:` entry added to `gene_body`
  once its real body size is confirmed against the executable.
seq:
  - id: genes
    type: gene_record
    repeat: until
    repeat-until: _.is_terminator
types:
  gene_record:
    seq:
      - id: tag
        type: str
        encoding: ascii
        size: 4
        doc: '"gene" for a real record, "gend" for the stream terminator.'
      - id: header
        type: gene_header
        if: not is_terminator
      - id: body
        type:
          switch-on: header.type_key
          cases:
            0: brain_lobe_gene
            256: biochemistry_receptor_gene
            257: biochemistry_emitter_gene
            258: biochemistry_reaction_gene
            259: biochemistry_half_life_gene
            260: biochemistry_initial_concentration_gene
            512: creature_stimulus_gene
            513: creature_genus_gene
            514: creature_appearance_gene
            515: creature_pose_gene
            516: creature_gait_gene
            517: creature_instinct_gene
            518: creature_pigment_gene
        if: not is_terminator
    instances:
      is_terminator:
        value: tag == "gend"

  gene_header:
    doc: C1GenomeGeneHeader (real Ghidra-recovered struct), the 6 bytes after the tag.
    seq:
      - id: family
        type: u1
        doc: 0=brain, 1=biochemistry, 2=creature. (3="organ" never occurs in real C1 data.)
      - id: subtype
        type: u1
      - id: sequence_number
        type: u1
        doc: Gene id, used for cross-referencing a GNO template's own gene list.
      - id: generation
        type: u1
      - id: switch_on_life_stage
        type: u1
      - id: flags
        type: u1
        doc: 0x1=mutable 0x2=dupable 0x4=deletable 0x8=maleonly 0x10=femaleonly 0x20=notexpressed
    instances:
      type_key:
        value: family * 256 + subtype

  # ---------------------------------------------------------------------
  # (0,0) Brain Lobe -- 112 bytes (CLobe::LoadGenome, 0x004025d0)
  # ---------------------------------------------------------------------
  brain_lobe_gene:
    doc: >
      Which of the engine's 9 fixed brain lobes this gene configures is
      purely POSITIONAL -- the Nth Brain Lobe gene encountered in the whole
      genome, in file order, always in the canonical order Perception,
      Drive, Source, Verb, Noun, GeneralSense, Decision, Attention,
      Concept. There is no self-identifying lobe field on disk.
    seq:
      - id: grid_x_offset
        type: u1
      - id: grid_y_offset
        type: u1
      - id: grid_width
        type: u1
      - id: grid_height
        type: u1
      - id: percept_flag
        type: u1
      - id: activation_threshold
        type: u1
      - id: activation_relaxation_selector
        type: u1
      - id: activation_baseline
        type: u1
      - id: input_gain
        type: u1
      - id: lobe_expression
        size: 8
        doc: 8x C1LobeRuleToken (SVRule bytecode), not further decoded here.
      - id: winner_take_all_flags
        type: u1
      - id: dendrite_growth_rule
        type: gene_connection_rule
      - id: dendrite_decay_rule
        type: gene_connection_rule

  gene_connection_rule:
    doc: >
      CLobeConnectionRule as it appears in a gene (47 bytes) --
      `CLobeConnectionRule::LoadFromGenome` (0x004023a0) expands this into
      the 60-byte in-memory struct (58 of which end up archived, see
      c1exp.ksy's c1_lobe_connection_rule), applying range-pair safety
      clamps (e.g. `connection_count_max`, if less than `_min` as read raw,
      is folded back up into `[_min, 255]` rather than left inverted) so
      that no mutation of these raw bytes can ever produce an invalid
      rule -- confirmed identically for count/baseline_weight/dendrite_state
      min/max pairs.
    seq:
      - id: target_lobe_index
        type: u1
      - id: connection_count_min
        type: u1
      - id: connection_count_max
        type: u1
      - id: count_distribution
        type: u1
      - id: target_cell_spread_radius
        type: u1
      - id: baseline_weight_min
        type: u1
      - id: baseline_weight_max
        type: u1
      - id: dendrite_state_min
        type: u1
      - id: dendrite_state_max
        type: u1
      - id: connection_mode
        type: u1
      - id: current_weight_decay_selector
        type: u1
      - id: target_weight_convergence_selector
        type: u1
      - id: baseline_weight_step_interval
        type: u1
      - id: dendrite_growth_interval
        type: u1
      - id: dendrite_growth_expression
        size: 8
      - id: dendrite_decay_interval
        type: u1
      - id: dendrite_decay_expression
        size: 8
      - id: current_weight_expression
        size: 8
      - id: target_weight_expression
        size: 8

  # ---------------------------------------------------------------------
  # Biochemistry genes (family 1) -- CBiochemistry::LoadGenome, 0x0042e940
  # ---------------------------------------------------------------------
  biochemistry_receptor_gene:
    doc: C1BiochemistryReceptorGene (real Ghidra-recovered struct), 8 bytes.
    seq:
      - id: target_domain_selector
        type: u1
        doc: Normalized `& 1` at load time -> Brain or Creature (GenomeLocusDomain).
      - id: tissue_index
        type: u1
      - id: locus_index
        type: u1
      - id: chemical_index
        type: u1
      - id: baseline
        type: u1
      - id: gain
        type: u1
      - id: threshold
        type: u1
      - id: flags
        type: u1

  biochemistry_emitter_gene:
    doc: C1BiochemistryEmitterGene (real Ghidra-recovered struct), 8 bytes.
    seq:
      - id: target_domain_selector
        type: u1
      - id: tissue_index
        type: u1
      - id: locus_index
        type: u1
      - id: chemical_index
        type: u1
      - id: threshold
        type: u1
      - id: emission_period
        type: u1
      - id: emission_amount
        type: u1
      - id: flags
        type: u1

  biochemistry_reaction_gene:
    doc: >
      C1BiochemistryReactionGene (real Ghidra-recovered struct), 9 bytes.
      NOTE the field order differs from the runtime CBiochemistry archive's
      own reaction record (c1exp.ksy's reaction_record): the gene puts
      tick_rate_selector LAST, the runtime record puts it in the middle.
    seq:
      - id: reactant_1_amount
        type: u1
      - id: reactant_1_chemical
        type: u1
      - id: reactant_2_amount
        type: u1
      - id: reactant_2_chemical
        type: u1
      - id: product_1_amount
        type: u1
      - id: product_1_chemical
        type: u1
      - id: product_2_amount
        type: u1
      - id: product_2_chemical
        type: u1
      - id: tick_rate_selector
        type: u1

  biochemistry_half_life_gene:
    doc: >
      C1BiochemistryHalfLifeGenePayload (real Ghidra-recovered struct), 256
      bytes -- one half-life selector per chemical index (0-255),
      positional, applying to the whole chemical table at once.
    seq:
      - id: half_life_selectors
        type: u1
        repeat: expr
        repeat-expr: 256

  biochemistry_initial_concentration_gene:
    doc: C1BiochemistryInitialConcentrationGenePayload (real Ghidra-recovered struct), 2 bytes.
    seq:
      - id: chemical_index
        type: u1
      - id: concentration
        type: u1

  # ---------------------------------------------------------------------
  # Creature genes (family 2) -- Creature::LoadGenome 0x00408960,
  # Skeleton::LoadGenome 0x0043c800
  # ---------------------------------------------------------------------
  creature_stimulus_gene:
    doc: >
      13 bytes (CONFIRMED directly from Creature::LoadGenome's decompile).
      `stimulus_index` selects one of the engine's 36 fixed built-in
      stimulus contexts (normalized mod 36); everything after it configures
      that context's behaviour and up to 4 chemical injections.
    seq:
      - id: stimulus_index
        type: u1
      - id: attention_activation
        type: u1
      - id: target_neuron_index
        type: u1
      - id: target_lobe_activation
        type: u1
      - id: flags
        type: u1
      - id: chemical_id_0
        type: u1
      - id: amount_0
        type: u1
      - id: chemical_id_1
        type: u1
      - id: amount_1
        type: u1
      - id: chemical_id_2
        type: u1
      - id: amount_2
        type: u1
      - id: chemical_id_3
        type: u1
      - id: amount_3
        type: u1

  creature_genus_gene:
    doc: C1CreatureGenusGenePayload (real Ghidra-recovered struct), 9 bytes.
    seq:
      - id: genus_selector
        type: u1
        doc: Norn/Grendel/Ettin/Shee, decoded via `classifier_base.genus = genus_selector + 1`.
      - id: mother_moniker
        type: u4
      - id: father_moniker
        type: u4

  creature_appearance_gene:
    doc: >
      C1CreatureAppearanceGenePayload (real Ghidra-recovered struct), 2
      bytes. `body_part_group_selector` (mod 5) picks one of 5 SYMMETRIC
      body-part groups (Head / Body / both legs / both arms / both tail
      parts) -- one gene sets the same sprite variant on every part in its
      group at once; there is no way to give a creature asymmetric
      left/right limbs via this gene type.
    seq:
      - id: body_part_group_selector
        type: u1
      - id: variant_index
        type: u1

  creature_pose_gene:
    doc: >
      16 bytes (CONFIRMED directly from Creature::LoadGenome's decompile):
      a pose-slot selector (mod 100) then 15 pose-string characters, each
      normalized into the set `?!X0123456789`.
    seq:
      - id: pose_slot_selector
        type: u1
      - id: pose_string
        type: str
        encoding: ascii
        size: 15

  creature_gait_gene:
    doc: >
      9 bytes (CONFIRMED directly from Creature::LoadGenome's decompile): a
      gait-slot selector (mod 8) then up to 8 sequence-step bytes (each mod
      100, decoded into a 2-digit '0'-'9' pair at runtime; a raw 0 ends the
      sequence early but the archived gene body is always the full 8
      bytes).
    seq:
      - id: gait_slot_selector
        type: u1
      - id: sequence_steps
        type: u1
        repeat: expr
        repeat-expr: 8

  creature_instinct_gene:
    doc: >
      9 bytes (CONFIRMED directly from Creature::LoadGenome's decompile):
      a 3-entry dream-replay queue (lobe index masked `&7` -- NOT the usual
      mod-9 normalization every other lobe-index consumer uses, so the
      9th lobe, Concept, is structurally unreachable as a dream-replay
      target -- then a neuron index within that lobe, modulo the lobe's
      real neuron count), then a decision-lobe neuron index and one dream
      chemical injection.
    seq:
      - id: dream_replay
        type: instinct_replay_slot
        repeat: expr
        repeat-expr: 3
      - id: decision_lobe_neuron_index
        type: u1
      - id: dream_chemical_index
        type: u1
      - id: dream_chemical_concentration
        type: u1

  instinct_replay_slot:
    seq:
      - id: lobe_index
        type: u1
      - id: neuron_index
        type: u1

  creature_pigment_gene:
    doc: C1CreaturePigmentGenePayload (real Ghidra-recovered struct), 2 bytes.
    seq:
      - id: pigment_channel
        type: u1
        doc: mod 3 -> Red/Green/Blue (C1CreaturePigmentChannel).
      - id: amount
        type: u1
