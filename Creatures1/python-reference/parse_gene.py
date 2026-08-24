#!/usr/bin/env python3
"""
Structural verifier for Creatures 1 .gen genome files (and the genome
payload embedded in .exp files after the CGenome archive header --
see parse_sfc.py's parse_cgenome, which returns the raw payload bytes
this module then parses).

Format confirmed 2026-08-22 by cross-referencing creatures.wiki's
community GEN_files documentation against REAL compiled code in the
live Ghidra database (CLobe::LoadGenome 0x004025d0,
CLobeRuleExpression::LoadFromGenome 0x00402250,
CLobeConnectionRule::LoadFromGenome 0x004023a0,
CBiochemistry::LoadGenome 0x0042e940, Creature::LoadGenome 0x00408960,
CGenome::FindNextMatchingGene 0x00419040) -- not taken from the wiki
alone. C1 uses "version 1" of the format: no dna2/dna3 file-level
header, file starts directly with the first gene's "gene" magic.

Overall structure: sequence of gene records, each starting with the
4-byte "gene" magic ("gend" terminates the stream), until EOF.

Common gene header (10 bytes, matches Ghidra's existing
C1GenomeGeneHeader exactly):
    tag: 4 bytes ("gene" or "gend")
    family: u8 (0=brain, 1=biochemistry, 2=creature, 3=organ;
             normalized mod 3 by the real loader if >2 -- i.e. only
             values 0-2 are meaningful for identifying gene TYPE, but
             family byte 3 legitimately appears on-disk for "organ"
             genes, which the loader's mod-3 normalization folds into
             "creature" family for search purposes -- kept raw here)
    subtype: u8 (meaning depends on family; normalized against a
             per-search modulus by the real loader, kept raw here)
    sequence_number: u8 (gene id, for GNO cross-reference)
    generation: u8
    switch_on_life_stage: u8
    flags: u8 (0x1=mutable 0x2=dupable 0x4=deletable 0x8=maleonly
               0x10=femaleonly 0x20=notexpressed)

Per-type body sizes (family, subtype) -> bytes, CONFIRMED against real
Ghidra LoadGenome/LoadFromGenome functions unless noted "(wiki only)":
    (0,0) Brain Lobe          = 112 bytes (CONFIRMED: CLobe::LoadGenome)
    (1,0) Biochemistry Receptor = 8 bytes (CONFIRMED: C1BiochemistryReceptorGene struct)
    (1,1) Biochemistry Emitter  = 8 bytes (CONFIRMED: C1BiochemistryEmitterGene struct)
    (1,2) Biochemistry Reaction = 9 bytes (CONFIRMED: C1BiochemistryReactionGene struct)
    (1,3) Biochemistry Half-lives = 256 bytes (CONFIRMED: CBiochemistry::LoadGenome's own
             decompile reads exactly 256 bytes in a flat loop; matches the pre-existing
             C1BiochemistryHalfLifeGenePayload struct)
    (1,4) Biochemistry Initial Concentration = 2 bytes (CONFIRMED: CBiochemistry::LoadGenome's
             own decompile reads exactly 2 bytes; C1BiochemistryInitialConcentrationGenePayload
             struct added this pass)
    (2,0) Creature Stimulus   = 13 bytes (CONFIRMED: Creature::LoadGenome)
    (2,1) Creature Genus      = 9 bytes (CONFIRMED: C1CreatureGenusGenePayload struct)
    (2,2) Creature Appearance = 2 bytes (CONFIRMED: C1CreatureAppearanceGenePayload struct,
             pre-existing in Ghidra from an earlier RE pass, cross-referenced against
             Skeleton::LoadGenome 0x0043c800's own plate comment and its real reads:
             body_part_selector mod5, variant_index mod10)
    (2,3) Creature Pose       = 16 bytes (CONFIRMED: Creature::LoadGenome)
    (2,4) Creature Gait       = 9 bytes (CONFIRMED: Creature::LoadGenome, on-disk size --
             the loader's OWN in-memory use can stop early at a sentinel
             byte, but the archived body is always the full fixed size)
    (2,5) Creature Instinct   = 9 bytes (CONFIRMED: Creature::LoadGenome)
    (2,6) Creature Pigment    = 2 bytes (CONFIRMED: C1CreaturePigmentGenePayload struct,
             pre-existing in Ghidra from an earlier RE pass, cross-referenced against
             Skeleton::LoadGenome 0x0043c800's own plate comment)

CORRECTION 2026-08-22: an earlier draft of this module included (3,0) "Organ" = 5 bytes,
taken from creatures.wiki's GEN_files page. That page's own table labels Organ genes
"Versions 2-3" -- i.e. a C2/C3-only concept, not part of real C1 data. Confirmed by two
independent checks: no "Organ"-named LoadGenome-style function exists anywhere in
Creatures.exe, and family byte 3 never appears in any of the 14 real specimens tested
(CGenome::FindNextMatchingGene's own family-normalization, `family %= 3` whenever
family > CREATURE(2), means a raw 3 would silently alias to family 0 "brain" if it ever
did appear -- so C1 itself has no real notion of a distinct family-3 "organ" type). Removed
from GENE_BODY_SIZES; family 3 is deliberately NOT mapped so it falls through to the
unknown-type recovery path below rather than asserting a wrong size.

Any (family, subtype) not in GENE_BODY_SIZES is unknown to this parser
-- see parse_gene_stream's fallback behavior.

SEMANTICS decoded so far (2026-08-22), beyond raw byte layout -- see
BRAIN_LOBE_NAMES and BODY_PART_GROUPS/BODY_PART_NAMES docstrings below for
full derivations:
    (0,0) Brain Lobe: lobe identity is purely POSITIONAL (the Nth Brain
        Lobe gene in file order), confirmed against CBrain::LoadGenome
        (0x00404560) and verified against all 14 real specimens in this
        repo -- always the canonical 9-lobe order.
    (2,2) Appearance: the selector byte picks a symmetric body-part GROUP
        (5 groups: Head/Body/Legs-both/Arms-both/Tail-both), not a single
        part -- confirmed by reading real bytes at Creatures.exe's
        g_genome_appearance_part_group_map (0x45ab40).
    (1,0)/(1,1)/(1,2)/(1,4)/(2,0) chemical index fields (0-255): decoded to
        real names via CHEMICAL_NAMES, sourced from the shipped
        windows/Creatures/allchemicals.str (a real length-prefixed MFC
        CArchive string table), cross-checked against BiochemKit.exe's own
        CMonitorPage::LoadChemicalNames (0x00404390), which loads this
        exact file by this exact name.
    (2,1) Genus: genus byte decoded to real breed name (Norn/Grendel/
        Ettin/Shee) via windows/Creatures/ClassifierNames.txt (community
        classifier reference), cross-checked against Skeleton::LoadGenome's
        (0x0043c800) `classifier_base.genus = gene_byte + 1` computation
        and against real specimens (dad1.gen=Norn, Gren.GEN=Grendel).
    (2,6) Pigment: channel byte (mod 3) decoded to Red/Green/Blue via
        Ghidra's pre-existing (already-correct) C1CreaturePigmentChannel
        enum, cross-checked against Skeleton::LoadGenome's real per-channel
        tint-averaging loop feeding BuildCreaturePaletteRemap.
    (1,0)/(1,1) Receptor/Emitter target_domain_selector: decoded to
        Brain/Creature via Ghidra's pre-existing GenomeLocusDomain enum,
        matching CBiochemistry::LoadGenome's own real normalization
        (raw & 1).
    (1,3) Half-lives: all 256 positional bytes decoded to a
        {chemical_name: half_life} dict via CHEMICAL_NAMES.
    (2,5) Instinct: lobe0/1/2 bytes decoded to real lobe names via
        BRAIN_LOBE_NAMES -- note these are masked &7 by the real loader
        (Creature::LoadGenome 0x00408960), NOT normalized mod 9 like every
        other lobe_index consumer, so CONCEPT(8) is structurally
        unreachable as an Instinct dream-replay target. dream_chemical
        byte decoded via CHEMICAL_NAMES.
"""
import struct
import sys

GENE_BODY_SIZES = {
    (0, 0): 112,   # Brain Lobe
    (1, 0): 8,     # Biochemistry Receptor
    (1, 1): 8,     # Biochemistry Emitter
    (1, 2): 9,     # Biochemistry Reaction
    (1, 3): 256,   # Biochemistry Half-lives
    (1, 4): 2,     # Biochemistry Initial Concentration
    (2, 0): 13,    # Creature Stimulus
    (2, 1): 9,     # Creature Genus
    (2, 2): 2,     # Creature Appearance
    (2, 3): 16,    # Creature Pose
    (2, 4): 9,     # Creature Gait
    (2, 5): 9,     # Creature Instinct
    (2, 6): 2,     # Creature Pigment
    # NOTE: no (3, *) entry -- "Organ" genes are a C2/C3-only concept, confirmed absent
    # from real C1 data (see module docstring's 2026-08-22 correction).
}

FAMILY_NAMES = {0: 'brain', 1: 'biochemistry', 2: 'creature', 3: 'organ'}

# Brain lobe name, by POSITIONAL index (the Nth (0,0) Brain Lobe gene
# encountered in the file, 0-based) -- NOT a field stored in the gene body
# itself. Confirmed 2026-08-22 two ways: (1) CBrain::LoadGenome
# (0x00404560) passes `this->lobe_count`, a simple counter incremented once
# per brain-lobe gene read IN FILE ORDER, as the lobe_index argument to
# CLobe::LoadGenome (0x004025d0); (2) CLobe::LoadGenome's own auto-grow
# switch on that lobe_index gives 7 of these 9 names real per-lobe minimum
# cell counts (Drive=16, Source=40, Verb=16, Noun=40, GeneralSense=32,
# Decision=16, Attention=40) that exactly match this same order's neuron
# counts independently confirmed from CBrain::Serialize's archive-format
# header sequence (which also gives Perception=112 and Concept=640, the 2
# lobes CLobe::LoadGenome's switch does NOT auto-grow -- presumably fixed
# layouts). A genome file's brain-lobe genes are only correctly labeled if
# they appear in this exact file order; there is no self-identifying lobe
# field on disk.
BRAIN_LOBE_NAMES = [
    'Perception', 'Drive', 'Source', 'Verb', 'Noun',
    'GeneralSense', 'Decision', 'Attention', 'Concept',
]

# C1BodyPartIndex names, by the real 0-13 index used throughout
# Skeleton::LoadGenome (0x0043c800)'s body_part_variant_by_index[] array and
# per-part sprite-resolution call sites.
BODY_PART_NAMES = [
    'Head', 'Body', 'LeftThigh', 'LeftShin', 'LeftFoot',
    'RightThigh', 'RightShin', 'RightFoot', 'LeftHumerus', 'LeftRadius',
    'RightHumerus', 'RightRadius', 'TailRoot', 'TailTip',
]

# Appearance gene (family=2 CREATURE, subtype=2) group semantics, confirmed
# 2026-08-22 by reading real bytes at g_genome_appearance_part_group_map
# (0x45ab40, Creatures.exe, int32_t[30] = 5 groups x 6 slots, -1-terminated).
# The gene's 1st byte (mod 5) selects a GROUP, not a single body part -- one
# Appearance gene sets the SAME sprite variant on every body part in its
# group at once, e.g. group 2 sets all 6 leg parts together (both legs
# always mirror -- there is no way to give a creature asymmetric left/right
# limbs via this gene type). Indices below are into BODY_PART_NAMES.
BODY_PART_GROUPS = [
    [0],                    # group 0: Head
    [1],                    # group 1: Body
    [4, 3, 2, 7, 6, 5],     # group 2: all 6 leg parts (both legs)
    [9, 8, 11, 10],         # group 3: all 4 arm parts (both arms)
    [13, 12],               # group 4: both tail parts
]

# Chemical index (0-255) -> real name, decoded 2026-08-22 directly from
# windows/Creatures/allchemicals.str -- a real length-prefixed MFC CArchive
# string table shipped with the retail install (1-byte length prefix per
# entry, sequential index = chemical index, preceded by a little-endian
# uint16 count = 256). Confirmed as ground truth, not a guess: BiochemKit's
# CMonitorPage::LoadChemicalNames (0x00404390) loads this exact file by
# this exact literal name from the game's main directory, and its own
# plate comment independently confirms the format ("little-endian uint16
# name count clamped to 256... reads each archive string with the kit's
# archive-string helper") -- matches byte-for-byte. Injector.exe and
# Science Kit.exe also reference this filename (chemical injection UI /
# gene chromosome viewer). Entries with no real name in the shipped table
# are still numbered ('73', '107', etc.) rather than invented.
CHEMICAL_NAMES = [
    '<NONE>', 'Pain', 'Need for Pleasure', 'Hunger',
    'Coldness', 'Hotness', 'Tiredness', 'Sleepiness',
    'Loneliness', 'Crowded', 'Fear', 'Boredom',
    'Anger', 'Sex Drive', 'not_allocated2', 'not_allocated3',
    'not_allocated4', 'Pain Increase', 'Need for Pleasure Increase', 'Hunger Increase',
    'Coldness Increase', 'Hotness Increase', 'Tiredness Increase', 'Sleepiness Increase',
    'Loneliness Increase', 'Crowded Increase', 'Fear Increase', 'Boredom Increase',
    'Anger Increase', 'Sex Drive Increase', 'not_allocated2++', 'not_allocated3++',
    'not_allocated4++', 'Pain Decrease (Endorphin)', 'Need for Pleasure Decrease', 'Hunger Decrease (Saccharin)',
    'Coldness Decrease', 'Hotness Decrease', 'Tiredness Decrease', 'Sleepiness Decrease',
    'Loneliness Decrease', 'Crowded Decrease', 'Fear Decrease', 'Boredom Decrease',
    'Anger Decrease', 'Sex Drive Decrease', 'not_allocated2--', 'not_allocated3--',
    'not_allocated4--', 'Reward', 'Punishment', 'Reinforcement',
    'ConASH', 'DecASH1', 'Reward Echo', 'Punish Echo',
    'Ageing', 'Starch', 'Glucose', 'Glycogen',
    'Waste Water', 'Hexokinase', 'Carbon Dioxide', 'Oestrogen',
    'Testosterone', 'Gonadotrophin', 'Progesterone', 'Glycotoxin',
    'Alcohol', 'Adrenaline', 'DecASH2', 'Vitamin E',
    'Vitamin C', '73', '74', '75',
    '76', '77', '78', '79',
    '80', '81', '82', '83',
    '84', '85', '86', '87',
    '88', '89', '90', 'Activase',
    'Turnase', 'Collapsase', '94', '95',
    '96', '97', '98', '99',
    'Energy', 'Adrenaline', 'Pain Killer', 'Cough Medicine',
    'Sleeping Pill', 'Wake-up Pill', 'Anti-oxidant', '107',
    '108', '109', '110', '111',
    '112', '113', '114', '115',
    '116', '117', '118', '119',
    '120', '121', '122', '123',
    '124', '125', '126', '127',
    '128', '129', '130', '131',
    '132', '133', '134', '135',
    '136', '137', '138', '139',
    '140', '141', '142', '143',
    '144', '145', '146', '147',
    '148', '149', '150', '151',
    '152', '153', '154', '155',
    '156', '157', '158', '159',
    '160', '161', '162', '163',
    '164', '165', '166', '167',
    '168', '169', '170', '171',
    '172', '173', '174', '175',
    '176', '177', '178', '179',
    '180', '181', '182', '183',
    '184', '185', '186', '187',
    '188', '189', '190', '191',
    '192', '193', '194', '195',
    '196', '197', '198', '199',
    '200', '201', '202', '203',
    '204', '205', '206', '207',
    '208', '209', '210', '211',
    '212', '213', '214', '215',
    '216', '217', '218', '219',
    '220', '221', '222', '223',
    '224', '225', '226', '227',
    '228', '229', '230', 'Geddonase',
    'Histamine A', 'Histamine B', 'Sleep toxin', 'Fever toxin',
    'unknown toxin', 'unknown toxin', 'unknown toxin', 'unknown toxin',
    'Antibody 0', 'Antibody 1', 'Antibody 2', 'Antibody 3',
    'Antibody 4', 'Antibody 5', 'Antibody 6', 'Antibody 7',
    'Antigen 0', 'Antigen 1', 'Antigen 2', 'Antigen 3',
    'Antigen 4', 'Antigen 5', 'Antigen 6', 'Antigen 7',
]


# Genus gene (family=2 CREATURE, subtype=1) genus byte -> real breed name.
# Confirmed 2026-08-22 via windows/Creatures/ClassifierNames.txt (a
# community-maintained COB/creature classifier reference shipped alongside
# the game): family 4 = "Creature", with genus sub-values 1=Norn,
# 2=Grendel, 3=Ettin, 4=Shee (Geat in later games). Skeleton::LoadGenome
# (0x0043c800) sets `classifier_base.genus = (raw_gene_genus_byte + 1)`,
# so the on-disk gene byte is 0-based: 0=Norn, 1=Grendel, 2=Ettin, 3=Shee.
# Cross-checked against real specimens: dad1.gen (a stock Norn) has genus
# byte 0; Gren.GEN (filename says it all) has genus byte 1.
GENUS_NAMES = ['Norn', 'Grendel', 'Ettin', 'Shee']

# Pigment gene (family=2 CREATURE, subtype=6) channel byte -> real name.
# Confirmed 2026-08-22: Ghidra's existing C1CreaturePigmentChannel enum
# already had real values (RED=0, GREEN=1, BLUE=2) -- just never wired
# into this parser. Cross-checked against Skeleton::LoadGenome's real
# read loop: channel byte mod 3, summed per-channel into
# pigment_sum_and_count[channel]/[channel+3], later averaged and fed as
# the first 3 (R,G,B tint) arguments to BuildCreaturePaletteRemap.
PIGMENT_CHANNEL_NAMES = ['Red', 'Green', 'Blue']

# Receptor/Emitter gene target_domain_selector byte -> real domain name.
# Confirmed 2026-08-22 via Ghidra's existing GenomeLocusDomain enum
# (BRAIN=0, CREATURE=1) plus CBiochemistry::LoadGenome's own real
# normalization: raw values 0/1 pass through as-is, any raw value >=2 is
# normalized by `value & 1` (odd->CREATURE, even->BRAIN) -- NOT a mod-2
# in the arithmetic sense, a bitwise AND, though the result is the same
# for this 1-byte field.
GENOME_LOCUS_DOMAIN_NAMES = ['Brain', 'Creature']


def locus_domain_name(raw):
    return GENOME_LOCUS_DOMAIN_NAMES[raw & 1]


def genus_name(index):
    return GENUS_NAMES[index] if 0 <= index < len(GENUS_NAMES) else f'UNKNOWN_GENUS_{index}'


def chem_name(index):
    """Chemical index -> name, tolerant of out-of-range/mod-normalized
    values (real loader code normalizes chemical bytes mod 256, which is a
    no-op for a u8 field, but keep this defensive for reuse elsewhere)."""
    return CHEMICAL_NAMES[index % 256]


class GeneFormatError(Exception):
    pass


def parse_gene_stream(data, verbose=True):
    """Parses a raw .gen-format byte stream (either a standalone .gen
    file's full contents, or the payload bytes from a .exp's embedded
    CGenome record). Returns a list of gene dicts and stops cleanly at
    the "gend" terminator, or raises GeneFormatError if the stream ends
    without one."""
    pos = 0
    n = len(data)
    genes = []
    unknown_type_counts = {}
    brain_lobe_count = 0  # positional counter, mirrors CBrain::LoadGenome's this->lobe_count

    def log(*a):
        if verbose:
            print(*a)

    while True:
        if pos + 4 > n:
            raise GeneFormatError(f"ran off end of data at {hex(pos)} looking for gene/gend tag")
        tag = data[pos:pos + 4]
        if tag == b'gend':
            log(f"gend terminator at {hex(pos)}, {len(genes)} genes parsed, "
                f"{n - pos - 4} trailing bytes")
            return genes, pos + 4
        if tag != b'gene':
            raise GeneFormatError(f"expected 'gene' or 'gend' tag at {hex(pos)}, got {tag!r}")
        if pos + 10 > n:
            raise GeneFormatError(f"truncated gene header at {hex(pos)}")
        family, subtype, sequence_number, generation, switch_on_life_stage, flags = \
            struct.unpack_from('<BBBBBB', data, pos + 4)
        header_end = pos + 10
        body_size = GENE_BODY_SIZES.get((family, subtype))
        if body_size is None:
            unknown_type_counts[(family, subtype)] = unknown_type_counts.get((family, subtype), 0) + 1
            # Unknown type: fall back to the same recovery the real
            # CGenome::FindNextMatchingGene uses on a non-matching gene
            # -- scan forward for the next gene/gend tag rather than
            # guessing a body size.
            scan = header_end
            while scan + 4 <= n and data[scan:scan + 4] not in (b'gene', b'gend'):
                scan += 1
            body = data[header_end:scan]
            genes.append(dict(family=family, subtype=subtype, sequence_number=sequence_number,
                               generation=generation, switch_on_life_stage=switch_on_life_stage,
                               flags=flags, body=body, body_size=len(body), known_type=False,
                               offset=pos))
            pos = scan
            continue
        if header_end + body_size > n:
            raise GeneFormatError(
                f"gene body at {hex(header_end)} (family={family} subtype={subtype} "
                f"needs {body_size} bytes) runs past end of data")
        body = data[header_end:header_end + body_size]
        gene = dict(family=family, subtype=subtype, sequence_number=sequence_number,
                    generation=generation, switch_on_life_stage=switch_on_life_stage,
                    flags=flags, body=body, body_size=body_size, known_type=True,
                    offset=pos)
        if (family, subtype) == (0, 0):
            # Brain Lobe gene -- name is purely positional (file order),
            # see BRAIN_LOBE_NAMES docstring above.
            if brain_lobe_count < len(BRAIN_LOBE_NAMES):
                gene['lobe_name'] = BRAIN_LOBE_NAMES[brain_lobe_count]
            else:
                gene['lobe_name'] = f'UNEXPECTED_LOBE_{brain_lobe_count}'
            gene['lobe_index'] = brain_lobe_count
            brain_lobe_count += 1
        elif (family, subtype) == (2, 2):
            # Appearance gene -- selector byte picks a symmetric body-part
            # GROUP (mod 5), not one part; see BODY_PART_GROUPS docstring.
            group_selector = body[0] % 5
            variant_index = body[1] % 10
            group = BODY_PART_GROUPS[group_selector]
            gene['group_selector'] = group_selector
            gene['variant_index'] = variant_index
            gene['affected_parts'] = [BODY_PART_NAMES[i] for i in group]
        elif (family, subtype) == (1, 0):
            # Biochemistry Receptor: organ(=target_domain_selector), tissue,
            # locus, chemical, threshold, nominal, gain, flags
            gene['domain_name'] = locus_domain_name(body[0])
            gene['chemical_name'] = chem_name(body[3])
        elif (family, subtype) == (1, 1):
            # Biochemistry Emitter: organ(=target_domain_selector), tissue,
            # locus, chemical, threshold, rate, gain, flags
            gene['domain_name'] = locus_domain_name(body[0])
            gene['chemical_name'] = chem_name(body[3])
        elif (family, subtype) == (1, 2):
            # Biochemistry Reaction: r1_amount, r1_chem, r2_amount, r2_chem,
            # p1_amount, p1_chem, p2_amount, p2_chem, rate
            gene['reactant1_name'] = chem_name(body[1])
            gene['reactant2_name'] = chem_name(body[3])
            gene['product1_name'] = chem_name(body[5])
            gene['product2_name'] = chem_name(body[7])
        elif (family, subtype) == (1, 3):
            # Biochemistry Half-lives: one byte per chemical index (0-255),
            # positional -- byte i is chemical i's half-life. Decode to a
            # {name: half_life} dict, dropping <NONE>(0) and any half-life
            # of 0 (meaning "instant decay", not "chemical present") only
            # from the summary view -- raw `body` still has everything.
            gene['half_lives_by_chemical'] = {
                CHEMICAL_NAMES[i]: body[i] for i in range(256)
            }
        elif (family, subtype) == (1, 4):
            # Biochemistry Initial Concentration: chemical, amount
            gene['chemical_name'] = chem_name(body[0])
        elif (family, subtype) == (2, 0):
            # Creature Stimulus: stimulus, significance, input, intensity,
            # features, chemical0, amount0, chemical1, amount1, chemical2,
            # amount2, chemical3, amount3
            gene['chemical_names'] = [chem_name(body[i]) for i in (5, 7, 9, 11)]
        elif (family, subtype) == (2, 1):
            # Creature Genus: genus, mom's moniker (char[4]), dad's moniker (char[4])
            gene['genus_name'] = genus_name(body[0])
            gene['moms_moniker'] = body[1:5].decode('ascii', 'replace')
            gene['dads_moniker'] = body[5:9].decode('ascii', 'replace')
        elif (family, subtype) == (2, 5):
            # Creature Instinct: lobe0, cell0, lobe1, cell1, lobe2, cell2,
            # decision_lobe_neuron_index, dream_chemical_index,
            # dream_chemical_concentration. lobe0/1/2 are masked &7 by the
            # real loader (Creature::LoadGenome 0x00408960) -- NOT
            # normalized mod 9 like every other lobe_index consumer in this
            # codebase, so CONCEPT(8) is structurally unreachable as an
            # Instinct dream-replay target even though the byte could
            # encode it (confirmed 2026-08-22, see the matching Ghidra
            # post-comment on 0x00408960).
            gene['lobe_names'] = [BRAIN_LOBE_NAMES[body[i] & 7] for i in (0, 2, 4)]
            gene['neuron_indices'] = [body[1], body[3], body[5]]
            gene['decision_lobe_neuron_index'] = body[6]
            gene['dream_chemical_name'] = chem_name(body[7])
        elif (family, subtype) == (2, 6):
            # Creature Pigment: channel (mod 3), amount
            gene['channel_name'] = PIGMENT_CHANNEL_NAMES[body[0] % 3]
        genes.append(gene)
        pos = header_end + body_size

    # unreachable


def summarize(genes):
    from collections import Counter
    known = Counter((g['family'], g['subtype']) for g in genes if g['known_type'])
    unknown = Counter((g['family'], g['subtype']) for g in genes if not g['known_type'])
    print("Known gene types:")
    for (fam, sub), count in sorted(known.items()):
        fam_name = FAMILY_NAMES.get(fam % 3, f'family{fam}')
        print(f"  family={fam:3d} ({fam_name:12s}) subtype={sub:3d}: {count:4d} genes")
    if unknown:
        print("UNKNOWN gene types (recovered via gene/gend rescan, body not decoded):")
        for (fam, sub), count in sorted(unknown.items()):
            print(f"  family={fam:3d} subtype={sub:3d}: {count:4d} genes")
    lobes = [g for g in genes if (g['family'], g['subtype']) == (0, 0)]
    if lobes:
        print(f"Brain Lobe genes ({len(lobes)} of expected 9), by file order -> real lobe name:")
        for g in lobes:
            print(f"  [{g['lobe_index']}] {g['lobe_name']}")
        if len(lobes) != 9 or [g['lobe_name'] for g in lobes] != BRAIN_LOBE_NAMES:
            print("  NOTE: does not match the expected canonical 9-lobe order -- "
                  "lobe_name assignments above are unreliable for this file "
                  "(see BRAIN_LOBE_NAMES docstring).")
    appearances = [g for g in genes if (g['family'], g['subtype']) == (2, 2)]
    if appearances:
        print(f"Appearance genes ({len(appearances)}), decoded group -> affected body parts:")
        for g in appearances:
            print(f"  group={g['group_selector']} variant={g['variant_index']} "
                  f"-> {', '.join(g['affected_parts'])}")
    genus_genes = [g for g in genes if (g['family'], g['subtype']) == (2, 1)]
    if genus_genes:
        print(f"Genus genes ({len(genus_genes)}):")
        for g in genus_genes:
            print(f"  genus={g['genus_name']} mom={g['moms_moniker']!r} dad={g['dads_moniker']!r}")
    pigment_genes = [g for g in genes if (g['family'], g['subtype']) == (2, 6)]
    if pigment_genes:
        print(f"Pigment genes ({len(pigment_genes)}):")
        for g in pigment_genes:
            print(f"  channel={g['channel_name']:5s} amount={g['body'][1]:3d}")
    instinct_genes = [g for g in genes if (g['family'], g['subtype']) == (2, 5)]
    if instinct_genes:
        print(f"Instinct genes ({len(instinct_genes)}):")
        for g in instinct_genes:
            print(f"  dream lobes={g['lobe_names']} neurons={g['neuron_indices']} "
                  f"decision_neuron={g['decision_lobe_neuron_index']} "
                  f"reinforcement_chemical={g['dream_chemical_name']} "
                  f"amount={g['body'][8]}")
    half_life_genes = [g for g in genes if (g['family'], g['subtype']) == (1, 3)]
    if half_life_genes:
        print(f"Half-lives genes ({len(half_life_genes)}), non-<NONE> non-zero entries only:")
        for g in half_life_genes:
            hl = g['half_lives_by_chemical']
            shown = {k: v for k, v in hl.items() if k != '<NONE>' and v != 0}
            print(f"  {len(shown)} chemicals with a nonzero half-life (of 255 possible)")
    chem_used = Counter()
    for g in genes:
        if 'chemical_name' in g:
            chem_used[g['chemical_name']] += 1
        if 'dream_chemical_name' in g:
            chem_used[g['dream_chemical_name']] += 1
        if 'chemical_names' in g:
            for n in g['chemical_names']:
                chem_used[n] += 1
        if 'reactant1_name' in g:
            for n in (g['reactant1_name'], g['reactant2_name'], g['product1_name'], g['product2_name']):
                chem_used[n] += 1
    if chem_used:
        print(f"Chemicals referenced by name across Receptor/Emitter/Reaction/InitialConcentration/"
              f"Stimulus/Instinct genes ({len(chem_used)} distinct):")
        for name, count in sorted(chem_used.items(), key=lambda kv: -kv[1]):
            print(f"  {name:30s} {count:4d}")
    domains_used = Counter(g['domain_name'] for g in genes if 'domain_name' in g)
    if domains_used:
        print(f"Receptor/Emitter target domains: {dict(domains_used)}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.gen-file>", file=sys.stderr)
        sys.exit(1)
    data = open(sys.argv[1], 'rb').read()
    print("file size:", len(data))
    try:
        genes, end_pos = parse_gene_stream(data)
    except GeneFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
    print(f"parsed {len(genes)} genes, stream ends at {hex(end_pos)} / file size {hex(len(data))}")
    summarize(genes)
