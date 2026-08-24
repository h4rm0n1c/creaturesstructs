meta:
  id: c1exp
  title: Creatures 1 exported creature (.exp)
  application: Creatures 1
  file-extension: exp
  endian: le
  license: CC0-1.0
doc: |
  A Creatures 1 `.exp` file (creature export, produced by the game's "export
  creature" feature and read back in by "import creature") is an MFC
  `CArchive` stream containing exactly TWO top-level polymorphic objects,
  back to back, with **no wrapping header at all** -- the file's very first
  two bytes are already the MFC "new class" tag (`0xFFFF`) for the first
  object:

    1. one `Creature` object (`Creature::Serialize`, 0x00407440) --
       Skeleton/Body/Limb chain, learned words, attention/stimulus history,
       Brain, Biochemistry, genome-tracking scalars, Instincts, the
       goal-direction weight matrix, Voice, and the creature's naming
       history record
    2. one `CGenome` object (`CGenome::Serialize`, 0x0041 85c0) -- the raw
       `.gen`-format gene-chunk stream for this creature (see the separate
       `c1gen.ksy`/`c1gno.ksy` spec for that payload's own internal format)

  This spec is a from-scratch rewrite against the real compiled game code
  (a live Ghidra decompilation of `Creatures.exe`), cross-checked
  byte-exact end-to-end against 9 real `.exp` specimens shipped with the
  game (including a mature/aged creature) -- every specimen parses with
  **zero bytes left over** after both top-level objects. It replaces an
  earlier version of this spec that (a) assumed a 6-byte file header and
  15 extra `u2` fields before the first real object -- neither exists; the
  file begins immediately with the `Creature` object -- and (b) read a
  brain lobe's header and its neuron records as one interleaved loop per
  lobe, which silently desynchronizes every lobe's data after the first
  one, since the real format reads *all* lobe headers first and *then* all
  lobe's neuron sections in a wholly separate second pass. Every field name
  below that names a real engine type (`C1BrainLobeArchivePrefix`,
  `CLobeConnectionRule`, `CBiochemistryEmitterRecord`, etc.) is taken
  directly from that type's real recovered struct layout in the executable,
  not guessed from context.

  ## The MFC polymorphic object-reference scheme

  Every object-valued field in this format (`Creature.brain`, `Body.gallery`,
  `Limb.next_in_chain`, ...) is written by `CArchive::WriteObject` /
  read by `CArchive::ReadObject`, whose wire format is a 2-byte tag:

  - `0x0000`: NULL -- no object.
  - `0xFFFF`: a **brand-new class**, named here for the first time in the
    stream -- a 2-byte schema number (always observed as `1` in this
    format), a 2-byte name length, and that many bytes of the ASCII class
    name follow, and then immediately after that, unconditionally, a new
    object of that class (its own field sequence, exactly like any other
    case that "has a body" below).
  - any value with the `0x8000` bit set (other than `0xFFFF` itself): the
    class was **already named** earlier in the stream (e.g. the 2nd+ `Limb`
    in a limb chain, reusing the "Limb" class registered by the 1st) -- no
    name follows, but a new object body still follows immediately.
  - any other nonzero value: a **back-reference** to an object that was
    already fully constructed earlier in the stream (e.g. every `Limb`'s
    and `Body`'s `gallery` field points back at the Skeleton's own single
    shared `CGallery`, and `CBiochemistry.owner` points back at the
    `Creature` currently being constructed) -- no body follows, just the
    index.

  Real MFC shares ONE 1-based index space between classes and objects
  (`CArchive::m_nMapCount`): every class registration and every object
  construction consumes the next sequential index in stream order. This
  spec models the tag mechanically (`obj_ref` type below) but, since a
  given `.exp` file's object graph is fully deterministic for a given
  field position (the same executable code path writes every `.exp` file),
  does not attempt to independently verify that a back-reference's target
  index actually resolves to the object this spec expects there.
seq:
  - id: creature
    type: obj_ref(true)
  - id: genome
    type: obj_ref(false)
types:
  # ---------------------------------------------------------------------
  # MFC CArchive polymorphic object reference (CArchive::ReadObject)
  # ---------------------------------------------------------------------
  obj_ref:
    doc: |
      One `CArchive::ReadObject`-shaped field. `is_creature` just selects
      which of the two top-level object kinds `.exp` can hold at THIS
      position -- every other object-valued field in this spec is a plain
      `type: obj_ref` with `is_creature` left at its default (false),
      because Kaitai Struct's `switch-on` needs a concrete value to
      dispatch on and every non-root object reference in this format
      already has exactly one expected class from context (documented at
      each call site by that field's own name).
    params:
      - id: is_creature
        type: bool
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type:
          switch-on: is_creature
          cases:
            true: creature
            false: genome
        if: has_body
    instances:
      is_null:
        value: tag == 0
      is_new_class:
        value: tag == 0xffff
      is_reused_class:
        value: (tag & 0x8000) != 0 and tag != 0xffff
      has_body:
        value: is_new_class or is_reused_class
      back_reference_index:
        value: tag
        if: not is_null and not has_body

  # A second, differently-parameterized obj_ref for the handful of call
  # sites that need to pick between more than the two top-level kinds.
  # Kaitai Struct has no "type value" parameter kind, so each distinct
  # family of possible bodies gets its own small swit便 type below
  # (obj_ref_gallery, obj_ref_bodypart, obj_ref_brain_or_null, ...)
  # rather than one fully generic dispatcher.
  obj_ref_gallery:
    doc: "An obj_ref whose body, when present, is always a CGallery."
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type: cgallery
        if: (tag == 0xffff) or ((tag & 0x8000) != 0 and tag != 0xffff)
    instances:
      is_null:
        value: tag == 0

  obj_ref_bodypart:
    doc: |
      An obj_ref whose body, when present, is either a `Body` (root of the
      skeleton) or a `Limb` (any other body part, including the recursive
      `next_in_chain` tail of a limb chain) -- distinguished by the real
      class name written on first use, since both share the same
      `BodyPart::Serialize` tail shape but Body additionally carries the
      two attachment matrices.
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type:
          switch-on: class_name
          cases:
            '"Body"': body_part_body
            '"Limb"': limb
        if: has_body
    instances:
      is_null:
        value: tag == 0
      has_body:
        value: (tag == 0xffff) or ((tag & 0x8000) != 0 and tag != 0xffff)
      # Reused-class references (2nd+ Limb) carry no name of their own;
      # every non-Body bodypart reference in this format is a Limb, so
      # that is the only name that needs to be recovered this way.
      class_name:
        value: 'tag == 0xffff ? new_class_name : "Limb"'

  # ---------------------------------------------------------------------
  # MFC string (AfxWriteStringLength's inverse): u1 length, escalating to
  # u2 then u4 for long strings.
  # ---------------------------------------------------------------------
  mfc_string:
    seq:
      - id: length1
        type: u1
      - id: length2
        type: u2
        if: length1 == 0xff
      - id: length4
        type: u4
        if: length1 == 0xff and length2 == 0xffff
      - id: text
        type: str
        encoding: ascii
        size: 'length1 != 0xff ? length1 : (length2 != 0xffff ? length2 : length4)'

  # ---------------------------------------------------------------------
  # Object::Serialize (0x00423ed0) -- shared prefix of every world object
  # ---------------------------------------------------------------------
  object_base:
    seq:
      - id: classifier_base
        type: u4
        doc: Packed family/genus/species/event classifier (ScriptClassifier).
      - id: bounds_mode
        type: u1
      - id: bounds_flags
        type: u1
      - id: movement_bounds_left
        type: s4
      - id: movement_bounds_top
        type: s4
      - id: movement_bounds_right
        type: s4
      - id: movement_bounds_bottom
        type: s4
      - id: bounds_reference_object
        type: obj_ref_gallery
        doc: >
          Really a generic Object* back-reference; reusing obj_ref_gallery
          here only because it shares the same "tag, optional body" shape
          and this field is always observed NULL in real .exp files (a
          freshly-exported single creature has no other object to bound
          itself against).
      - id: current_interaction_event_id
        type: u1
      - id: gallery_ptr
        type: obj_ref_gallery
        doc: >
          For the Skeleton itself, this is the ONE real CGallery object in
          the whole file -- every Body/Limb's own `gallery` field, and
          every CImage's `gallery` field, is a back-reference to this same
          object.
      - id: timer_period
        type: s4
      - id: timer_countdown
        type: s4
      - id: caos_object_pointer
        type: obj_ref_gallery
        doc: Always observed NULL in real .exp files.
      - id: continuous_sound_descriptor
        type: u4
      - id: caos_var1
        type: u4
      - id: caos_var2
        type: u4
      - id: caos_var3
        type: u4
      - id: scripts
        type: script_list

  script_list:
    doc: DeserializeScriptsForClassifier (0x0041a8e0).
    seq:
      - id: num_scripts
        type: s4
      - id: scripts
        type: script_entry
        repeat: expr
        repeat-expr: num_scripts

  script_entry:
    seq:
      - id: classifier
        type: u4
      - id: source
        type: mfc_string

  # ---------------------------------------------------------------------
  # CGallery::Serialize (0x004424d0)
  # ---------------------------------------------------------------------
  cgallery:
    seq:
      - id: num_images
        type: u4
      - id: sprite_file_id
        type: str
        encoding: ascii
        size: 4
        doc: >
          The 4-character sprite-file stem (e.g. a body-part sprite set's
          base filename), stored as 4 raw ASCII bytes read where the
          engine's own type is a packed u4.
      - id: header_record_index
        type: s4
      - id: reference_count
        type: u4
      - id: images
        type: cgallery_image
        repeat: expr
        repeat-expr: num_images

  cgallery_image:
    doc: >
      CImage::Serialize (0x00442870), read directly by CGallery's own
      virtual-call loop -- not itself a full polymorphic MFC object, just a
      back-reference to the owning CGallery followed by 9 raw bytes.
    seq:
      - id: gallery
        type: u2
        doc: Always a back-reference (obj_ref tag) to the owning CGallery.
      - id: cache_flags
        type: u1
      - id: width
        type: s4
      - id: height
        type: s4
      - id: sprite_data_offset
        type: u4

  # ---------------------------------------------------------------------
  # BodyPart tail (0x00415f30), Body (0x00416290), Limb (0x00416060)
  # ---------------------------------------------------------------------
  entity_tail:
    doc: >
      The part of Entity::Serialize (0x00415090) after the `gallery` field,
      which BodyPart::Serialize reads directly rather than as a nested
      Entity object.
    seq:
      - id: current_image_index
        type: u1
      - id: image_index_base
        type: u1
      - id: render_plane
        type: s4
      - id: world_x
        type: s4
      - id: world_y
        type: s4
      - id: has_animation_sequence
        type: u1
      - id: animation_sequence_cursor_offset
        type: u1
        if: has_animation_sequence != 0
      - id: animation_sequence
        size: 32
        if: has_animation_sequence != 0

  body_part_tail:
    doc: BodyPart::Serialize (0x00415f30) -- shared by Body and Limb.
    seq:
      - id: gallery
        type: obj_ref_gallery
      - id: entity
        type: entity_tail
      - id: pose_frame_index
        type: u4
      - id: attachment_frame_index
        type: u4

  body_part_body:
    doc: >
      Body::Serialize (0x00416290) -- BodyPart tail plus two 6x10
      attachment matrices (join-X and join-Y, one row per limb-chain slot,
      one column per pose frame).
    seq:
      - id: bodypart
        type: body_part_tail
      - id: join_x_by_limb_chain_and_view
        size: 60
      - id: join_y_by_limb_chain_and_view
        size: 60

  limb:
    doc: >
      Limb::Serialize (0x00416060) -- BodyPart tail, 10 frames x 2
      anchor points (A and B) x 2 axes = 40 attachment bytes, then a
      recursive `next_in_chain` reference continuing this limb's chain
      (e.g. thigh -> shin, radius -> humerus), NULL at the chain's end.
    seq:
      - id: bodypart
        type: body_part_tail
      - id: anchor_a_by_frame
        size: 20
      - id: anchor_b_by_frame
        size: 20
      - id: next_in_chain
        type: obj_ref_bodypart

  # ---------------------------------------------------------------------
  # Skeleton::Serialize tail (0x0043ade0) -- after Object::Serialize
  # ---------------------------------------------------------------------
  skeleton_tail:
    seq:
      - id: genome_source_filename
        type: u4
      - id: mother_moniker
        type: u4
      - id: father_moniker
        type: u4
      - id: body
        type: obj_ref_bodypart
      - id: limb_chain_heads
        type: obj_ref_bodypart
        repeat: expr
        repeat-expr: 6
        doc: >
          Head, left arm (radius+humerus), right arm, left leg
          (shin+thigh), right leg, tail -- any chain the creature's genome
          doesn't grow (most commonly the tail) is NULL here.
      - id: facing_direction
        type: u1
      - id: down_foot
        type: u1
      - id: down_foot_x
        type: s4
      - id: down_foot_y
        type: s4
      - id: normal_render_plane
        type: s4
      - id: current_pose
        type: mfc_string
      - id: drive_threshold_state
        type: u1
      - id: eyes_open
        type: u1
      - id: sleep_indicator_active
        type: u1
      - id: poses
        type: mfc_string
        repeat: expr
        repeat-expr: 100
      - id: gait_sequences
        type: mfc_string
        repeat: expr
        repeat-expr: 8

  # ---------------------------------------------------------------------
  # Creature::Serialize (0x00407440)
  # ---------------------------------------------------------------------
  creature:
    seq:
      - id: object
        type: object_base
      - id: skeleton
        type: skeleton_tail
      - id: learned_words
        type: learned_word_record
        repeat: expr
        repeat-expr: 80
      - id: attention_history
        type: attention_record
        repeat: expr
        repeat-expr: 40
      - id: stimulus_history
        type: stimulus_context
        repeat: expr
        repeat-expr: 36
      - id: brain
        type: obj_ref_brain
      - id: biochemistry
        type: obj_ref_biochemistry
      - id: genome_gender
        type: u1
      - id: genome_life_stage
        type: u1
      - id: biochemistry_tick
        type: u4
      - id: gamete_genome_source_filename
        type: u4
      - id: child_genome_source_filename
        type: u4
      - id: death_state
        type: u1
      - id: age_ticks
        type: u4
      - id: num_instincts
        type: u4
      - id: dream_countdown
        type: u4
      - id: instincts
        type: obj_ref_instinct
        repeat: expr
        repeat-expr: num_instincts
      - id: goal_direction_weight_matrix
        type: goal_direction_weight_matrix
      - id: voice
        type: voice_tail
        doc: >
          NOTE: the decompile appears to show a `ReadObject(SimpleObject)`
          call for a `sleep_indicator_object` here, between the matrix and
          Voice -- confirmed NOT actually present on the LOAD path in any
          of 9 real specimens tested (Voice starts immediately at the
          matrix's end with no intervening tag); not modelled here.
      - id: register_state
        type: creature_register
        doc: >
          CCreatureRegister::Serialize (0x00406a60), called unconditionally
          right after Voice, outside the normal load/save branch.

  learned_word_record:
    seq:
      - id: response_word
        type: mfc_string
      - id: recognized_word
        type: mfc_string
      - id: reinforcement
        type: u4

  attention_record:
    seq:
      - id: last_x
        type: s4
      - id: last_y
        type: s4

  stimulus_context:
    doc: CreatureStimulusContext, 12 bytes -- 4 fixed bytes + an 8-byte tail.
    seq:
      - id: stimulus_index
        type: u1
      - id: response_index
        type: u1
      - id: intensity
        type: u1
      - id: flags
        type: u1
      - id: tail
        size: 8

  creature_register:
    doc: >
      CCreatureRegister::Serialize (0x00406a60) -- 10 plain length-prefixed
      strings for C1CreatureHistory. The last 4 fields' real meaning is not
      yet confirmed against the decompile (Ghidra's own recovered
      C1CreatureHistory struct also leaves them as unknown_history_0N).
    seq:
      - id: genome_moniker
        type: mfc_string
      - id: display_name
        type: mfc_string
      - id: father_moniker
        type: mfc_string
      - id: mother_moniker
        type: mfc_string
      - id: birthday
        type: mfc_string
      - id: birthplace
        type: mfc_string
      - id: unknown_history_06
        type: mfc_string
      - id: unknown_history_07
        type: mfc_string
      - id: unknown_history_08
        type: mfc_string
      - id: unknown_history_09
        type: mfc_string

  neuron_address:
    doc: CreatureBrainNeuronAddress (8 bytes).
    seq:
      - id: lobe_index
        type: u4
      - id: neuron_index
        type: u4

  obj_ref_instinct:
    doc: An obj_ref whose body, when present, is a CInstinct.
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type: cinstinct
        if: (tag == 0xffff) or ((tag & 0x8000) != 0 and tag != 0xffff)

  cinstinct:
    doc: >
      CInstinct::Serialize (0x00407070) -- fixed 40 bytes on the wire (the
      in-memory CInstinct struct's own vptr is not archived).
    seq:
      - id: dream_replay_addresses
        type: neuron_address
        repeat: expr
        repeat-expr: 3
      - id: decision_lobe_neuron_index
        type: u4
      - id: dream_chemical_index
        type: u4
      - id: dream_chemical_concentration
        type: u4
      - id: dream_step_index
        type: u4

  goal_direction_weight_matrix:
    doc: >
      CreatureGoalDirectionWeightMatrix (2562 bytes): a 2-byte alignment
      prefix (not itself meaningful data) then a flat 40x16 grid of u4
      per-goal-direction weights.
    seq:
      - id: alignment_prefix
        size: 2
      - id: goal_score_weights
        type: u4
        repeat: expr
        repeat-expr: 640

  voice_tail:
    doc: >
      Voice::Serialize (0x00445600) -- fixed 580 bytes on the wire (the
      in-memory Voice struct's vptr, normalized_phrase and its cursor, and
      accumulated_sound_delay_ticks are runtime-only and not archived).
    seq:
      - id: trigram_selection_masks
        type: u4
        repeat: expr
        repeat-expr: 81
        doc: Three 27-entry groups of trigram-selection bitmasks.
      - id: sound_id_by_selection
        type: u4
        repeat: expr
        repeat-expr: 32
      - id: sound_duration_by_selection
        type: u4
        repeat: expr
        repeat-expr: 32

  # ---------------------------------------------------------------------
  # CBrain::Serialize (0x00402c50)
  # ---------------------------------------------------------------------
  obj_ref_brain:
    doc: An obj_ref whose body, when present, is a CBrain.
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type: cbrain
        if: (tag == 0xffff) or ((tag & 0x8000) != 0 and tag != 0xffff)

  cbrain:
    doc: |
      Two separate passes over the same `num_lobes` lobes, NOT interleaved
      -- this is the exact bug in the earlier version of this spec (and in
      an earlier pass of this project's own from-scratch parser): reading
      lobe 0's header, then lobe 0's neurons, then lobe 1's header, ...
      silently desynchronizes every lobe after the first, because the real
      format is: ALL lobe headers first, THEN all lobes' neuron sections.
      With this fixed, every lobe's `num_neurons` lands exactly on
      Creatures 1's well-documented built-in brain architecture (Perception
      112, Drive 16, Source 40, Verb 16, Noun 40, GeneralSense 32,
      Decision 16, Attention 40, Concept 640).
    seq:
      - id: num_lobes
        type: u4
      - id: lobe_headers
        type: cbrain_lobe_header
        repeat: expr
        repeat-expr: num_lobes
      - id: lobe_neuron_sections
        type: cbrain_neuron_section(lobe_headers[_index].num_neurons)
        repeat: expr
        repeat-expr: num_lobes

  cbrain_lobe_header:
    seq:
      - id: prefix
        type: c1_brain_lobe_archive_prefix
      - id: dendrite_growth_rule
        type: c1_lobe_connection_rule
      - id: dendrite_decay_rule
        type: c1_lobe_connection_rule
      - id: num_neurons
        type: u4
      - id: total_connection_count
        type: u4

  c1_brain_lobe_archive_prefix:
    doc: C1BrainLobeArchivePrefix, 40 bytes (real Ghidra-recovered struct).
    seq:
      - id: grid_x_offset
        type: u4
      - id: grid_y_offset
        type: u4
      - id: grid_width
        type: u4
      - id: grid_height
        type: u4
      - id: percept_flag
        type: u4
      - id: active_fraction
        type: u1
      - id: late_phase_token_state
        size: 4
      - id: activation_threshold
        type: u1
      - id: activation_relaxation_selector
        type: u1
      - id: activation_baseline
        type: u1
      - id: input_gain
        type: u1
      - id: lobe_expression
        size: 10
        doc: 10x C1LobeRuleToken -- SVRule bytecode, not further decoded here.
      - id: winner_take_all_flags
        type: u1

  c1_lobe_connection_rule:
    doc: >
      CLobeConnectionRule as archived (58 of its 60 in-memory bytes -- the
      trailing 2-byte `padding_3a` is confirmed NOT archived, per this
      project's own root-cause note on CBrain::Serialize's 164-bytes/lobe
      count: 40 (prefix) + 58 + 58 (two rules) + 4 + 4 (counts) = 164).
    seq:
      - id: target_lobe_index
        type: u4
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
        size: 10
        doc: CLobeRuleExpression (10x C1LobeRuleToken), not further decoded.
      - id: dendrite_decay_interval
        type: u1
      - id: dendrite_decay_expression
        size: 10
      - id: current_weight_expression
        size: 10
      - id: target_weight_expression
        size: 10

  cbrain_neuron_section:
    params:
      - id: num_neurons
        type: u4
    seq:
      - id: neurons
        type: cbrain_neuron
        repeat: expr
        repeat-expr: num_neurons

  cbrain_neuron:
    seq:
      - id: prefix
        type: c1_brain_neuron_archive_prefix
      - id: dendrite_group_0
        type: connection_group
      - id: dendrite_group_1
        type: connection_group

  c1_brain_neuron_archive_prefix:
    doc: C1BrainNeuronArchivePrefix, 6 bytes (real Ghidra-recovered struct).
    seq:
      - id: grid_x
        type: u1
      - id: grid_y
        type: u1
      - id: firing_strength
        type: u1
      - id: activation
        type: u1
      - id: winner_take_all_excluded
        type: u1
      - id: source_lobe_index
        type: u1

  connection_group:
    doc: C1BrainConnectionGroupHeader (5 bytes) + that many connection records.
    seq:
      - id: connection_count
        type: u1
      - id: connection_begin_index
        type: u4
      - id: connections
        type: connection_record
        repeat: expr
        repeat-expr: connection_count

  connection_record:
    doc: C1BrainConnectionArchiveRecord, 10 bytes (real Ghidra-recovered struct).
    seq:
      - id: target_neuron_index
        type: s4
      - id: target_grid_x
        type: u1
      - id: target_grid_y
        type: u1
      - id: current_weight
        type: u1
      - id: target_weight
        type: u1
      - id: baseline_weight
        type: u1
      - id: dendrite_state
        type: u1

  # ---------------------------------------------------------------------
  # CBiochemistry::Serialize (0x0042dbe0)
  # ---------------------------------------------------------------------
  obj_ref_biochemistry:
    doc: An obj_ref whose body, when present, is a CBiochemistry.
    seq:
      - id: tag
        type: u2
      - id: new_class_schema
        type: u2
        if: tag == 0xffff
      - id: new_class_name_length
        type: u2
        if: tag == 0xffff
      - id: new_class_name
        type: str
        encoding: ascii
        size: new_class_name_length
        if: tag == 0xffff
      - id: body
        type: cbiochemistry
        if: (tag == 0xffff) or ((tag & 0x8000) != 0 and tag != 0xffff)

  cbiochemistry:
    seq:
      - id: owner
        type: u2
        doc: Always a back-reference (obj_ref tag) to the enclosing Creature.
      - id: num_emitter_genes
        type: u4
      - id: num_receptor_genes
        type: u4
      - id: num_reaction_genes
        type: u4
      - id: chemicals
        type: chemical_record
        repeat: expr
        repeat-expr: 256
      - id: emitters
        type: emitter_record
        repeat: expr
        repeat-expr: num_emitter_genes
      - id: receptors
        type: receptor_record
        repeat: expr
        repeat-expr: num_receptor_genes
      - id: reactions
        type: reaction_record
        repeat: expr
        repeat-expr: num_reaction_genes

  chemical_record:
    doc: C1BiochemistryChemicalArchiveRecord, 2 bytes.
    seq:
      - id: concentration
        type: u1
      - id: half_life_selector
        type: u1

  emitter_record:
    doc: >
      CBiochemistryEmitterRecord as archived (8 of its 12 in-memory bytes --
      the trailing 4-byte `source_locus` pointer is rebuilt at load time by
      `resolve_genome_locus`, confirmed not archived directly from the LOAD
      branch of CBiochemistry::Serialize's decompile).
    seq:
      - id: target_domain
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

  receptor_record:
    doc: >
      CBiochemistryReceptorRecord as archived (8 of its 12 in-memory bytes
      -- the trailing 4-byte `target_locus` pointer is rebuilt at load time,
      same as emitter_record's `source_locus`).
    seq:
      - id: target_domain
        type: u1
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

  reaction_record:
    doc: CBiochemistryReactionRecord, 9 bytes (real Ghidra-recovered struct).
    seq:
      - id: reactant_1_amount
        type: u1
      - id: reactant_1_chemical
        type: u1
      - id: reactant_2_amount
        type: u1
      - id: reactant_2_chemical
        type: u1
      - id: tick_rate_selector
        type: u1
      - id: product_1_amount
        type: u1
      - id: product_1_chemical
        type: u1
      - id: product_2_amount
        type: u1
      - id: product_2_chemical
        type: u1

  # ---------------------------------------------------------------------
  # CGenome::Serialize (0x004185c0)
  # ---------------------------------------------------------------------
  genome:
    doc: >
      CGenome is a top-level object in its own right, written immediately
      after the whole Creature record (register_state included) completes
      -- NOT nested inside Creature/CBiochemistry, despite a `ReadObject`
      call that appears (in the decompile) to be inside CBiochemistry's own
      body; confirmed by locating this object's real archive tag directly
      and finding it lands after Creature's real end in every specimen
      tested. `payload` is a standalone gene-chunk stream in the same
      format as a `.gen` file on disk -- see the separate genome spec.
    seq:
      - id: payload_size
        type: u4
      - id: source_filename
        type: u4
      - id: genome_gender
        type: u4
      - id: genome_life_stage
        type: u1
      - id: payload
        size: payload_size
