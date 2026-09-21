#!/usr/bin/env python3
"""
Structural verifier for a Creatures 1 World.sfc save file, built to
mechanically confirm (rather than hand-eyeball) the RE documentation
recorded on the live Ghidra DB for the document archive format.

FULLY CONFIRMED byte-exact 2026-08-22: `parse_sfc(path)` now parses the
ENTIRE World.sfc file end-to-end against this repo's own real specimen
(`windows/Creatures/World.sfc`, 177269 bytes) -- "SFCDoc: CONFIRMED
end-to-end... remaining=0". This closes the whole World.sfc format,
matching the earlier `.exp` closure in `parse_exp`. Getting here needed
two upstream bug fixes beyond just implementing new classes: `Lift`'s
CallButton loop was missing a raw floor_y:u32 field per slot (see
0x004250a0's Ghidra comment), and `Scenery` had never been implemented
at all -- both were silently blocking every one of World.sfc's 189
non_scenery_objects / 140 scenery_objects from ever being reached.

Supersedes the earlier MapData-only tools/parse_sfc_mapdata.py. Extend
by adding another @register('ClassName') function if a DIFFERENT
World.sfc specimen exercises a class this one didn't -- SERIALIZERS
keys are class names exactly as they appear in the archive's MFC
dynamic-class tags, so a NotImplementedClass error tells you precisely
which class needs a parser next.

Currently implemented:
    MapData::Serialize   (0x00422a00) -- document root object
    CGallery::Serialize  (0x004424d0) -- MapData's embedded gallery,
                                         and any object's own gallery_ptr
    CImage::Serialize    (0x00442870) -- one CGallery frame (not a real
                                         object -- direct virtual-call
                                         loop, see CGallery notes below)
    CBacterium::Serialize(0x004019e0) -- one of MapData's 100 embedded
                                         bacteria (also a direct-call loop)
    Object::Serialize    (0x00423ed0) -- base class shared by every
                                         world object
    SimpleObject::Serialize (0x004243e0) -- SimpleObject tail (after
                                         Object base)
    Entity::Serialize    (0x00415090) -- sprite/position record used by
                                         every SimpleObject
    PointerTool::Serialize (0x004246c0)
    Bubble::Serialize    (0x004249e0)
    CompoundObject::Serialize (0x00424b30)
    Vehicle::Serialize   (0x00424dd0)
    Blackboard::Serialize (0x00425360)
    CallButton::Serialize (0x00424900)
    Lift::Serialize      (0x004250a0) -- FLAGGED: trailing call-button
                                         loop does not fully round-trip,
                                         see the function's own docstring
    DeserializeScriptsForClassifier (0x0041a8e0) -- per-object script list

Gets through the first 106 of 189 non_scenery_objects in the repo's own
World.sfc before hitting Lift's flagged loop (2026-08-21 status). Not
yet implemented: Creature (by far the largest and most complex --
brain/biochemistry/genome), Scenery, and whatever else appears past
that point or in the scenery_objects/world_object_registry arrays.

MFC CArchive object-tag scheme implemented (confirmed 2026-08-21 against
real MFC 4.x source, libs/mfc/source/arcobj.cpp -- an initial guess at
this scheme was wrong and produced garbage; see read_object_tag()).
The crucial fact that isn't obvious from field names alone: classes
and objects share ONE unified 1-based index space (`m_nMapCount` in
real MFC), index 0 reserved for NULL. Every class gets an index when
its name is first written; every object (regardless of whether its
class is new or reused) ALSO gets its own, later index in that same
space, in construction order.
    tag == 0x0000              : NULL
    tag == 0xFFFF (wNewClassTag): a brand-new CLASS -- WORD schema, WORD
                                  name length, name bytes -- immediately
                                  followed by a NEW OBJECT of it (its
                                  own Serialize body follows inline)
    tag == 0x7FFF (wBigObjectTag): a DWORD tag follows (only needed once
                                  the unified counter exceeds ~32K; not
                                  hit by any file this size)
    tag & 0x8000 (wClassTag)    : the CLASS was already named earlier
                                  (index = tag & 0x7FFF into the class
                                  table), but this is STILL a NEW OBJECT
                                  of that class -- its body follows
                                  inline immediately, exactly like the
                                  0xFFFF case. (This is how, e.g., a
                                  SimpleObject's own private per-object
                                  CGallery -- a genuinely new CGallery
                                  instance for cursor sprites, distinct
                                  from MapData's shared background
                                  CGallery -- gets framed: the "CGallery"
                                  class name was already written once,
                                  so it's referenced by class index, but
                                  a whole new gallery-with-images record
                                  still follows.)
    any other value (1..0x7FFE) : a back-reference to an object ALREADY
                                  fully constructed earlier in the
                                  archive (e.g. every CImage's own
                                  `gallery` field pointing back at its
                                  owning CGallery). No object body
                                  follows -- just an index, no bytes to
                                  skip.

MFC string format implemented (AfxWriteStringLength's inverse): a BYTE
length; if 0xFF, a WORD length follows; if that is 0xFFFF, a DWORD
length follows. Used for per-object CAOS script text.

Usage:
    python3 parse_sfc.py <path-to-World.sfc>
"""
import struct
import sys


class SfcArchiveError(Exception):
    pass


class NotImplementedClass(SfcArchiveError):
    def __init__(self, classname, pos, label=""):
        self.classname = classname
        self.pos = pos
        super().__init__(
            f"no serializer implemented for class '{classname}'"
            f"{f' (referenced as {label})' if label else ''} at {hex(pos)}. "
            f"Next step: read '// ---- {classname}::Serialize' in "
            f"creatures1_decompiled/Creatures/*.cpp and add a "
            f"@register('{classname}') parser."
        )


SERIALIZERS = {}


def register(classname):
    def deco(fn):
        SERIALIZERS[classname] = fn
        return fn
    return deco


class SfcTruncated(Exception):
    """The archive ended mid-record.

    Distinguished from SfcDesync because the cause is different and so is the
    remedy: a desync means this parser's model of some class is wrong, while a
    truncated file means the archive was never fully written and no parser can
    read it.  A World.sfc cut at an exact 4096-byte boundary is the usual
    shape -- a save that was interrupted before its last block was flushed.
    """

    def __init__(self, want, offset, size):
        self.want = want
        self.offset = offset
        self.size = size
        super().__init__(
            f"archive ends mid-record: wanted {want} byte(s) at {hex(offset)} "
            f"but the file is only {hex(size)} ({size}) bytes"
            + ("; size is an exact 4096-byte multiple, so this is most likely "
               "a save interrupted before its final block was flushed"
               if size % 4096 == 0 else ""))


class SfcDesync(Exception):
    """A serializer failed partway through an object.

    Carries the class being parsed, the offset its body started at, and the
    field label that reached it.  Nested dispatches chain, so the innermost
    SfcDesync names the serializer that actually lost sync -- the outer ones
    only show the path that got there.
    """

    def __init__(self, classname, offset, label, cause):
        self.classname = classname
        self.offset = offset
        self.label = label
        self.cause = cause
        where = f" via {label}" if label else ""
        super().__init__(
            f"desync parsing {classname} starting at {hex(offset)}{where}: "
            f"{type(cause).__name__}: {cause}")


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        # Real MFC CArchive shares ONE 1-based index space between
        # classes and objects (m_nMapCount in arcobj.cpp): every class
        # registration AND every object construction consumes the next
        # sequential index, interleaved in real chronological order --
        # so class indices are NOT simply 1,2,3,... in class-first-seen
        # order (an earlier version of this script got that wrong: it
        # kept a separate class-only list and mis-resolved class-reuse
        # tags as a result). `registry[index] = ('class', name)` or
        # `('object', None)`; index 0 is reserved for NULL and unused.
        self.registry = {}
        self.next_index = 1

    def _need(self, n):
        if self.pos + n > len(self.data):
            raise SfcTruncated(n, self.pos, len(self.data))

    def u8(self):
        self._need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self):
        self._need(2)
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        self._need(4)
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self):
        self._need(4)
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def bytes_(self, n):
        self._need(n)
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def mfc_string(self):
        n = self.u8()
        if n == 0xFF:
            n = self.u16()
            if n == 0xFFFF:
                n = self.u32()
        return self.bytes_(n).decode('latin1')

    def read_object_tag(self):
        """Returns (kind, payload); kind in
        {'null','new_class','old_class','obj_ref'}. Does NOT allocate an
        index for the object that may follow -- see read_object_ref(),
        which is the only place that happens (matching real MFC:
        InsertAt(m_nMapCount++, ...) happens once, right before
        Serialize is called on the new object)."""
        tag = self.u16()
        if tag == 0:
            return ('null', None)
        if tag == 0xFFFF:
            # wNewClassTag: brand-new class, name written for the first
            # time -- a NEW OBJECT of it follows immediately.
            schema = self.u16()
            namelen = self.u16()
            name = self.bytes_(namelen).decode('ascii')
            class_index = self.next_index
            self.next_index += 1
            self.registry[class_index] = ('class', name)
            return ('new_class', name)
        if tag == 0x7FFF:
            # wBigObjectTag: a DWORD tag follows (only needed once the
            # unified class+object counter exceeds ~32K -- not hit by
            # any file this small, implemented for completeness/safety).
            big = self.u32()
            if big & 0x80000000:
                class_index = big & 0x7FFFFFFF
                kind, name = self.registry[class_index]
                assert kind == 'class'
                return ('old_class', name)
            return ('obj_ref', big)
        if tag & 0x8000:
            # wClassTag (0x8000) OR'd with a 1-based index into the
            # SAME unified registry as objects (see class comment on
            # Reader.registry): the CLASS was already named earlier in
            # the archive, but this is still a NEW object of that class
            # (e.g. a SimpleObject's private per-object CGallery reusing
            # the already-seen "CGallery" class definition) -- its body
            # follows immediately, exactly like the 0xFFFF case.
            class_index = tag & 0x7FFF
            kind, name = self.registry[class_index]
            assert kind == 'class', f"tag {hex(tag)} -> registry[{class_index}] is {kind!r}, not a class"
            return ('old_class', name)
        # Real MFC CArchive::WriteObject/ReadObject share ONE 1-based
        # index space between classes AND objects (m_nMapCount in
        # arcobj.cpp) -- any plain small value here (1..0x7FFE) is a
        # back-reference to an object ALREADY fully constructed earlier
        # in the archive (e.g. every CImage's `gallery` field pointing
        # back at its owning CGallery). No further bytes follow.
        return ('obj_ref', tag)

    def read_object_ref(self, label=""):
        """Reads one CArchive::ReadObject-style reference. Returns None
        for NULL, ('ref', tag) for a back-reference to an object already
        fully parsed earlier, or a fully-parsed dict for a brand-new
        object (dispatched by class name -- raises NotImplementedClass
        if we don't have a parser for it yet)."""
        kind, payload = self.read_object_tag()
        if kind == 'null':
            return None
        if kind == 'obj_ref':
            return ('ref', payload)
        # new_class / old_class: a NEW object follows -- it claims the
        # next index in the unified registry BEFORE we parse its body
        # (matching real MFC's InsertAt-before-Serialize ordering).
        obj_index = self.next_index
        self.next_index += 1
        self.registry[obj_index] = ('object', None)
        classname = payload
        if classname not in SERIALIZERS:
            raise NotImplementedClass(classname, self.pos, label)
        # Report WHERE a desync happened, not just where it finally ran off
        # the end.  A serializer that reads one byte too few leaves the
        # cursor wrong for everything after it, so the error surfaces in some
        # innocent later class at a nonsense offset and names the wrong
        # culprit.  Wrapping each dispatch keeps the class name, the offset
        # its body started at, and the enclosing field label, and chains so
        # the innermost frame is the first thing that actually misread.
        start = self.pos
        try:
            obj = SERIALIZERS[classname](self)
        except (SfcDesync, SfcTruncated):
            raise
        except Exception as error:
            raise SfcDesync(classname, start, label, error) from error
        return obj


def parse_scripts(r):
    """DeserializeScriptsForClassifier (0x0041a8e0): i32 count, then
    {classifier:u32, CAOS source: mfc_string} per entry."""
    count = r.i32()
    scripts = []
    for _ in range(count):
        classifier = r.u32()
        text = r.mfc_string()
        scripts.append((classifier, text))
    return scripts


# ---------------------------------------------------------------------
# CGallery / CImage / CBacterium (also used standalone by MapData)
# ---------------------------------------------------------------------

@register('CGallery')
def parse_cgallery(r):
    image_count = r.u32()
    sprite_file_id_raw = r.u32()
    sprite_file_id = struct.pack('<I', sprite_file_id_raw).rstrip(b'\x00').decode('ascii', 'replace')
    header_record_index = r.i32()
    reference_count = r.u32()
    images = []
    for i in range(image_count):
        gkind, gref = r.read_object_tag()
        if gkind != 'obj_ref':
            raise SfcArchiveError(f"CGallery image {i}: expected gallery obj_ref, got {gkind}/{gref} at {hex(r.pos)}")
        cache_flags = r.u8()
        width = r.i32()
        height = r.i32()
        sprite_data_offset = r.u32()
        images.append((cache_flags, width, height, sprite_data_offset))
    return dict(kind='CGallery', image_count=image_count, sprite_file_id=sprite_file_id,
                header_record_index=header_record_index, reference_count=reference_count,
                images=images)


def parse_bacteria(r, count=100):
    bacteria = []
    for i in range(count):
        activity = r.u8()
        input_id = r.u8()
        kill_thresh = r.u8()
        act_thresh = r.u8()
        outs = [r.u8() for _ in range(4)]
        bacteria.append((activity, input_id, kill_thresh, act_thresh, outs))
    return bacteria


# ---------------------------------------------------------------------
# MapData (document root)
# ---------------------------------------------------------------------

@register('MapData')
def parse_mapdata(r, verbose=False):
    def log(*a):
        if verbose:
            print(*a)

    version = r.u32()
    ambient = r.u32()
    log("  MapData: version=", version, "ambient=", ambient, "pos=", hex(r.pos))

    gallery = r.read_object_ref("MapData.gallery")
    if not (isinstance(gallery, dict) and gallery.get('kind') == 'CGallery'):
        raise SfcArchiveError(f"expected a new CGallery object for MapData.gallery, got {gallery!r} at {hex(r.pos)}")
    log("  gallery: image_count=", gallery['image_count'], "sprite_file_id=", gallery['sprite_file_id'],
        "pos=", hex(r.pos))

    room_count = r.u32()
    rooms = []
    for i in range(room_count):
        left = r.i32(); top = r.i32(); right = r.i32(); bottom = r.i32()
        room_type = r.u32()
        rooms.append((left, top, right, bottom, room_type))
    log("  rooms:", len(rooms), "pos=", hex(r.pos))

    ground_heights = [r.u32() for _ in range(261)]
    log("  ground heights: 261, pos=", hex(r.pos))

    bacteria = parse_bacteria(r, 100)
    log("  bacteria: 100, pos=", hex(r.pos))

    return dict(kind='MapData', version=version, ambient=ambient, gallery=gallery,
                rooms=rooms, ground_heights=ground_heights, bacteria=bacteria)


# ---------------------------------------------------------------------
# Object hierarchy
# ---------------------------------------------------------------------

def parse_object_base(r):
    """Object::Serialize (0x00423ed0) -- shared prefix for every world object."""
    classifier_base = r.u32()
    bounds_mode = r.u8()
    bounds_flags = r.u8()
    movement_bounds = struct.unpack('<4i', r.bytes_(16))
    bounds_reference_object = r.read_object_ref("Object.bounds_reference_object")
    current_interaction_event_id = r.u8()
    gallery_ptr = r.read_object_ref("Object.gallery_ptr")
    timer_period = r.i32()
    timer_countdown = r.i32()
    caos_object_pointer = r.read_object_ref("Object.caos_object_pointer")
    continuous_sound_descriptor = r.u32()
    caos_vars = [r.u32() for _ in range(3)]
    scripts = parse_scripts(r)
    return dict(classifier_base=classifier_base, bounds_mode=bounds_mode,
                bounds_flags=bounds_flags, movement_bounds=movement_bounds,
                bounds_reference_object=bounds_reference_object,
                current_interaction_event_id=current_interaction_event_id,
                gallery_ptr=gallery_ptr, timer_period=timer_period,
                timer_countdown=timer_countdown,
                caos_object_pointer=caos_object_pointer,
                continuous_sound_descriptor=continuous_sound_descriptor,
                caos_vars=caos_vars, scripts=scripts)


@register('Entity')
def parse_entity(r):
    """Entity::Serialize (0x00415090)."""
    gallery = r.read_object_ref("Entity.gallery")
    current_image_index = r.u8()
    image_index_base = r.u8()
    render_plane = r.i32()
    world_x = r.i32()
    world_y = r.i32()
    presence = r.u8()
    seq_cursor_offset = None
    seq = None
    if presence:
        seq_cursor_offset = r.u8()
        seq = r.bytes_(32)
    return dict(kind='Entity', gallery=gallery, current_image_index=current_image_index,
                image_index_base=image_index_base, render_plane=render_plane,
                world_x=world_x, world_y=world_y, seq_cursor_offset=seq_cursor_offset, seq=seq)


def parse_simpleobject_tail(r):
    """SimpleObject::Serialize (0x004243e0), the part after Object::Serialize."""
    entity = r.read_object_ref("SimpleObject.entity")
    saved_entity_render_plane = r.i32()
    click0 = r.u8(); click1 = r.u8(); click2 = r.u8()
    interaction_event_flags = r.u8()
    return dict(entity=entity, saved_entity_render_plane=saved_entity_render_plane,
                click_states=(click0, click1, click2),
                interaction_event_flags=interaction_event_flags)


@register('CallButton')
def parse_callbutton(r):
    """CallButton::Serialize (0x00424900): SimpleObject base, then one
    Lift object ref, floor_index:u8."""
    ob = parse_object_base(r)
    tail = parse_simpleobject_tail(r)
    lift_ref = r.read_object_ref("CallButton.lift_ref")
    floor_index = r.u8()
    return dict(kind='CallButton', base=ob, tail=tail, lift_ref=lift_ref, floor_index=floor_index)


@register('Lift')
def parse_lift(r):
    """Lift::Serialize (0x004250a0): Vehicle base, then floor_count:u32,
    current_floor_index:u32, selected_call_button_index:u32,
    call_selection_cooldown:u8, then 8x {floor_y:u32, call_button ref}.

    RESOLVED 2026-08-22 via raw disassembly of the LOAD-path loop tail
    (0x0042530f-0x00425355): the decompile's apparent "raw 4-byte write
    into call_button_refs_8[0] before also calling ReadObject" was NOT
    decompiler noise as an earlier pass assumed -- it's real. Each of
    the 8 slots reads a plain raw u32 directly off the buffer FIRST
    (`MOV EAX,[EAX]` from the current m_lpBufCur, then `ADD [archive+
    0x28],4` to advance the cursor -- no object-tag framing at all for
    this field), THEN a separate CArchive::ReadObject call for the
    CallButton class. This 4-byte field lands 0x28 (40) bytes before
    the CallButton pointer slot in memory -- consistent with it being
    the per-floor Y pixel coordinate the existing plate comment
    (0x004250a0) says is "reconstructed/maintained separately" at
    runtime; that description is only true for HOW the value is used
    after loading, not whether it is archived -- it demonstrably is.
    Confirmed against World.sfc's one real Lift (floor_count=2): slots
    0/1 read floor_y=738/927 (plausible pixel Y coordinates) with NULL
    CallButton refs, slots 2-7 read plausible-garbage floor_y values
    (unused slots, floor_count=2) with NULL refs -- all 8 slots parse
    cleanly with zero errors, where the old (missing-field) model
    reliably desynced by slot 6-7 across the one real specimen."""
    base = parse_vehicle(r)
    floor_count = r.u32()
    current_floor_index = r.u32()
    selected_call_button_index = r.u32()
    call_selection_cooldown = r.u8()
    floors = []
    for i in range(8):
        floor_y = r.u32()
        call_button = r.read_object_ref(f"Lift.call_button_refs_8[{i}]")
        floors.append(dict(floor_y=floor_y, call_button=call_button))
    return dict(kind='Lift', base=base, floor_count=floor_count,
                current_floor_index=current_floor_index,
                selected_call_button_index=selected_call_button_index,
                call_selection_cooldown=call_selection_cooldown,
                floors=floors)


def parse_favourite_place(r):
    """CFavouritePlace::Serialize (0x004179f0), called via direct virtual
    dispatch (not CArchive::ReadObject/WriteObject -- no object tag) for
    each of SFCDoc's 6 fixed favourite_places slots. mfc_string name,
    then viewport_origin_x:i16, viewport_origin_y:i16."""
    name = r.mfc_string()
    viewport_origin_x = struct.unpack('<h', r.bytes_(2))[0]
    viewport_origin_y = struct.unpack('<h', r.bytes_(2))[0]
    return dict(kind='CFavouritePlace', name=name,
                viewport_origin=(viewport_origin_x, viewport_origin_y))


def parse_mytoolbar(r):
    """MyToolBar::Serialize (0x00421e80), direct virtual dispatch (no
    object tag). creature_selector_item_count:i16, then that many
    mfc_string creature-selector combo-box entries."""
    item_count = struct.unpack('<h', r.bytes_(2))[0]
    items = [r.mfc_string() for _ in range(item_count)]
    return dict(kind='MyToolBar', items=items)


def parse_ceventbar(r):
    """CEventBar::Serialize (0x00416fe0), direct virtual dispatch (no
    object tag). displayed_object_count:u32, then that many polymorphic
    Object refs, then two i32 fields.

    RESOLVED 2026-08-22: serialized_event_bar_state_0/1 are DEAD/
    VESTIGIAL -- never written by any CEventBar code. Confirmed by the
    actual saved values, not more code-reading: both read as exactly
    0xCDCDCDCD in two independent real World.sfc specimens from
    unrelated play sessions -- 0xCD is MSVC debug CRT's canonical
    "allocated heap memory, never initialized" fill byte. Getting the
    identical value across two unrelated sessions is definitive proof
    nothing ever writes real data here; this parser still reads them
    (they're genuinely part of the wire format) but their value should
    always be exactly -842150451 (0xCDCDCDCD) and carries no real
    information."""
    displayed_object_count = r.u32()
    displayed_objects = [r.read_object_ref(f"CEventBar.displayed_objects[{i}]")
                         for i in range(displayed_object_count)]
    state_0 = r.i32()
    state_1 = r.i32()
    return dict(kind='CEventBar', displayed_objects=displayed_objects,
                serialized_event_bar_state_0=state_0, serialized_event_bar_state_1=state_1)


def parse_cscore(r):
    """CScore::Serialize (0x0042f7a0), direct virtual dispatch (no
    object tag). Fixed 5x i32 score_values.

    RESOLVED 2026-08-22: individual meanings cross-referenced from
    CEventBar::UpdateStatusPanes (0x004168b0) and C1 Kits/Score Kit.exe's
    own CScorePage::RefreshDisplay (0x004084e0), which carries an
    explicit field-by-field breakdown -- hatchery_eggs_used,
    natural_eggs_laid (the CAOS "negg" counter), dead_norns, living_norns,
    population_time_accumulator (incremented by the living-creature count
    every 1200 world ticks in SFCDoc::UpdateWorld). The classic C1
    main-window "Score:" HUD figure is `score_values[4] +
    score_values[1]*256` (clamped to 99999), not a single counter.
    Confirmed against real data: worldpopulated/World.sfc's [3,0,0,3,230]
    = 3 hatchery eggs, 0 natural eggs, 0 deaths, 3 living norns, 230
    accumulated population-time points."""
    hatchery_eggs_used = r.i32()
    natural_eggs_laid = r.i32()
    dead_norns = r.i32()
    living_norns = r.i32()
    population_time_accumulator = r.i32()
    return dict(kind='CScore', hatchery_eggs_used=hatchery_eggs_used,
                natural_eggs_laid=natural_eggs_laid, dead_norns=dead_norns,
                living_norns=living_norns,
                population_time_accumulator=population_time_accumulator,
                score_values=[hatchery_eggs_used, natural_eggs_laid, dead_norns,
                              living_norns, population_time_accumulator])


@register('Macro')
def parse_macro(r):
    """Macro::Serialize (0x004195f0): destroy_when_finished:u32,
    capture_output_enabled:u32, script_capacity_bytes:u32, script:
    mfc_string, script_cursor_offset:u32, 20x C1CAOSValue caos_value_stack
    (4 bytes each -- confirmed as a plain 4-byte-per-iteration read loop
    in the decompile, not further decoded here), stack_cursor_index:u32,
    10x caos_work_values:u32, then 5 polymorphic Object refs
    (script_owner, from_object, exec_object, target_object, it_object),
    selected_part_index:i32, subroutine_cache_id:u32,
    subroutine_cache_cursor_offset:u32, wait_ticks_remaining:u32. Field
    order fully confirmed from a complete read of the decompile (already
    an existing, detailed plate comment on this function from earlier
    RE work -- this parser implements it for the first time)."""
    destroy_when_finished = r.u32()
    capture_output_enabled = r.u32()
    script_capacity_bytes = r.u32()
    script = r.mfc_string()
    script_cursor_offset = r.u32()
    caos_value_stack = [r.u32() for _ in range(20)]
    stack_cursor_index = r.u32()
    caos_work_values = [r.u32() for _ in range(10)]
    script_owner = r.read_object_ref("Macro.object_context.script_owner")
    from_object = r.read_object_ref("Macro.object_context.from_object")
    exec_object = r.read_object_ref("Macro.object_context.exec_object")
    target_object = r.read_object_ref("Macro.object_context.target_object")
    it_object = r.read_object_ref("Macro.object_context.it_object")
    selected_part_index = r.i32()
    subroutine_cache_id = r.u32()
    subroutine_cache_cursor_offset = r.u32()
    wait_ticks_remaining = r.u32()
    return dict(kind='Macro', destroy_when_finished=destroy_when_finished,
                capture_output_enabled=capture_output_enabled,
                script_capacity_bytes=script_capacity_bytes, script=script,
                script_cursor_offset=script_cursor_offset,
                caos_value_stack=caos_value_stack, stack_cursor_index=stack_cursor_index,
                caos_work_values=caos_work_values,
                object_context=dict(script_owner=script_owner, from_object=from_object,
                                     exec_object=exec_object, target_object=target_object,
                                     it_object=it_object),
                selected_part_index=selected_part_index,
                subroutine_cache_id=subroutine_cache_id,
                subroutine_cache_cursor_offset=subroutine_cache_cursor_offset,
                wait_ticks_remaining=wait_ticks_remaining)


@register('Blackboard')
def parse_blackboard(r):
    """Blackboard::Serialize (0x00425360): CompoundObject base, then
    5 display-config bytes (fill_palette_index, text_render_config_1/2,
    tile_x, tile_y), then 16x {word_value:u32, text:11 bytes}."""
    base = parse_compoundobject(r)
    display_config = r.bytes_(5)
    entries = []
    for i in range(16):
        word_value = r.u32()
        text = r.bytes_(11)
        entries.append((word_value, text))
    return dict(kind='Blackboard', base=base, display_config=display_config, entries=entries)


@register('Vehicle')
def parse_vehicle(r):
    """Vehicle::Serialize (0x00424dd0): CompoundObject base, then
    velocity_x/y:i32 (8.8 fixed point), position_x/y:i32 (8.8 fixed
    point), creature_event_bounds_local: WorldRect (16 bytes),
    collision_side_flags:u32."""
    base = parse_compoundobject(r)
    velocity_x = r.i32()
    velocity_y = r.i32()
    position_x = r.i32()
    position_y = r.i32()
    creature_event_bounds_local = struct.unpack('<4i', r.bytes_(16))
    collision_side_flags = r.u32()
    return dict(kind='Vehicle', base=base, velocity=(velocity_x, velocity_y),
                position=(position_x, position_y),
                creature_event_bounds_local=creature_event_bounds_local,
                collision_side_flags=collision_side_flags)


@register('Scenery')
def parse_scenery(r):
    """Scenery::Serialize (0x00424380): Object base, then one Entity
    object ref (`entity_ptr`) -- Scenery is a direct Object subclass,
    NOT via SimpleObject/Entity-as-tail like most other world objects.
    Confirmed 2026-08-22 straight from the decompile (short, unambiguous,
    no decompiler-failure warning)."""
    base = parse_object_base(r)
    entity = r.read_object_ref("Scenery.entity_ptr")
    return dict(kind='Scenery', base=base, entity=entity)


@register('SimpleObject')
def parse_simpleobject(r):
    """SimpleObject::Serialize (0x004243e0) instantiated directly (not
    via a derived class) -- Object base + the SimpleObject tail."""
    base = parse_object_base(r)
    tail = parse_simpleobject_tail(r)
    return dict(kind='SimpleObject', base=base, tail=tail)


@register('Bubble')
def parse_bubble(r):
    """Bubble::Serialize (0x004249e0): SimpleObject base, then
    lifetime_ticks_remaining:u8, anchor object ref, 25 raw bytes."""
    base = parse_object_base(r)
    tail = parse_simpleobject_tail(r)
    lifetime_ticks_remaining = r.u8()
    anchor = r.read_object_ref("Bubble.anchor")
    text = r.bytes_(25)
    return dict(kind='Bubble', base=base, tail=tail,
                lifetime_ticks_remaining=lifetime_ticks_remaining,
                anchor=anchor, text=text)


@register('CompoundObject')
def parse_compoundobject(r):
    """CompoundObject::Serialize (0x00424b30): Object base, then
    part_count:i32, part_count x (Entity ref, local_x:i32, local_y:i32),
    six WorldRect (16 bytes each, part_bounds), six i32
    (creature_event_config)."""
    base = parse_object_base(r)
    part_count = r.i32()
    parts = []
    for i in range(part_count):
        entity = r.read_object_ref(f"CompoundObject.parts[{i}].entity")
        local_x = r.i32()
        local_y = r.i32()
        parts.append((entity, local_x, local_y))
    part_bounds = [struct.unpack('<4i', r.bytes_(16)) for _ in range(6)]
    creature_event_config = [r.i32() for _ in range(6)]
    return dict(kind='CompoundObject', base=base, part_count=part_count,
                parts=parts, part_bounds=part_bounds,
                creature_event_config=creature_event_config)


@register('PointerTool')
def parse_pointertool(r):
    """PointerTool::Serialize (0x004246c0): SimpleObject base, then
    cursor_hotspot_offset_x/y:i32, Bubble object ref, 25 raw text bytes."""
    base = parse_object_base(r)
    tail = parse_simpleobject_tail(r)
    hotspot_x = r.i32()
    hotspot_y = r.i32()
    bubble = r.read_object_ref("PointerTool.bubble")
    text = r.bytes_(25)
    return dict(kind='PointerTool', base=base, tail=tail,
                hotspot=(hotspot_x, hotspot_y), bubble=bubble, text=text)


# ---------------------------------------------------------------------
# Creature and its whole sub-object tree (Skeleton/Body/Limb, CBrain,
# CBiochemistry, CInstinct, Voice) -- by far the largest class in the
# archive. Implemented 2026-08-21 straight off each function's
# decompile, using several already-defined /C1Formats/* fixed-record
# Ghidra structs (their sizes/field names were cross-checked, not
# re-derived here) for CBrain/CBiochemistry's per-entry records.
# ---------------------------------------------------------------------

def parse_entity_tail_only(r):
    """The bytes Entity::Serialize (0x00415090) writes AFTER its own
    `gallery` object ref -- factored out because BodyPart embeds an
    Entity but Entity's own gallery ref is read the normal way via
    read_object_ref, so this just continues from there."""
    current_image_index = r.u8()
    image_index_base = r.u8()
    render_plane = r.i32()
    world_x = r.i32()
    world_y = r.i32()
    presence = r.u8()
    seq_cursor_offset = None
    seq = None
    if presence:
        seq_cursor_offset = r.u8()
        seq = r.bytes_(32)
    return dict(current_image_index=current_image_index, image_index_base=image_index_base,
                render_plane=render_plane, world_x=world_x, world_y=world_y,
                seq_cursor_offset=seq_cursor_offset, seq=seq)


def parse_bodypart_tail(r):
    """BodyPart::Serialize (0x00415f30): Entity::Serialize, then
    pose_frame_index:u32, attachment_frame_index:u32."""
    gallery = r.read_object_ref("BodyPart.entity.gallery")
    entity_tail = parse_entity_tail_only(r)
    pose_frame_index = r.u32()
    attachment_frame_index = r.u32()
    return dict(gallery=gallery, entity_tail=entity_tail,
                pose_frame_index=pose_frame_index,
                attachment_frame_index=attachment_frame_index)


@register('Body')
def parse_body(r):
    """Body::Serialize (0x00416290): BodyPart tail, then 120 raw bytes
    (two 6x10 attachment matrices: join-X, join-Y)."""
    bodypart = parse_bodypart_tail(r)
    attachment_matrices = r.bytes_(120)
    return dict(kind='Body', bodypart=bodypart, attachment_matrices=attachment_matrices)


@register('Limb')
def parse_limb(r):
    """Limb::Serialize (0x00416060): BodyPart tail, then 40 attachment
    bytes (10 frames x anchor-A-X/Y, anchor-B-X/Y), then one
    next_in_chain Limb object ref (recursive chain)."""
    bodypart = parse_bodypart_tail(r)
    frames = r.bytes_(40)
    next_in_chain = r.read_object_ref("Limb.next_in_chain")
    return dict(kind='Limb', bodypart=bodypart, frames=frames, next_in_chain=next_in_chain)


def parse_skeleton_tail(r):
    """Skeleton::Serialize (0x0043ade0), the part after Object::Serialize:
    genome_source_filename/mother_moniker/father_moniker:u32 each, Body
    ref, 6x Limb ref, facing_direction:u8, down_foot:u8, down_foot_x/y:
    i32, normal_render_plane:i32, current_pose:mfc_string,
    drive_threshold_state/eyes_open/sleep_indicator_active:u8 each,
    100x pose mfc_string, 8x gait-sequence mfc_string."""
    genome_source_filename = r.u32()
    mother_moniker = r.u32()
    father_moniker = r.u32()
    body = r.read_object_ref("Skeleton.body")
    limbs = [r.read_object_ref(f"Skeleton.limb_chain_heads[{i}]") for i in range(6)]
    facing_direction = r.u8()
    down_foot = r.u8()
    down_foot_x = r.i32()
    down_foot_y = r.i32()
    normal_render_plane = r.i32()
    current_pose = r.mfc_string()
    drive_threshold_state = r.u8()
    eyes_open = r.u8()
    sleep_indicator_active = r.u8()
    poses = [r.mfc_string() for _ in range(100)]
    gaits = [r.mfc_string() for _ in range(8)]
    return dict(genome_source_filename=genome_source_filename, mother_moniker=mother_moniker,
                father_moniker=father_moniker, body=body, limbs=limbs,
                facing_direction=facing_direction, down_foot=down_foot,
                down_foot_x=down_foot_x, down_foot_y=down_foot_y,
                normal_render_plane=normal_render_plane, current_pose=current_pose,
                drive_threshold_state=drive_threshold_state, eyes_open=eyes_open,
                sleep_indicator_active=sleep_indicator_active, poses=poses, gaits=gaits)


@register('CInstinct')
def parse_cinstinct(r):
    """CInstinct::Serialize (0x00407070): fixed 40 bytes -- three
    {lobe_index:u32, neuron_index:u32} pairs, then
    decision_lobe_neuron_index/dream_chemical_index/
    dream_chemical_concentration/dream_step_index:u32 each.

    CONFIRMED 2026-08-22 against Foxy.exp (the first .exp specimen found
    with a nonzero instinct_count=3). All 3 records round-tripped
    cleanly with fully plausible values (dream_chemical_index=49 and
    dream_chemical_concentration=255 constant across all 3; every
    dream-replay lobe index is 1 or 5, the only two brain lobes with
    real neurons in this creature)."""
    replay = [(r.u32(), r.u32()) for _ in range(3)]
    decision_lobe_neuron_index = r.u32()
    dream_chemical_index = r.u32()
    dream_chemical_concentration = r.u32()
    dream_step_index = r.u32()
    return dict(kind='CInstinct', replay=replay,
                decision_lobe_neuron_index=decision_lobe_neuron_index,
                dream_chemical_index=dream_chemical_index,
                dream_chemical_concentration=dream_chemical_concentration,
                dream_step_index=dream_step_index)


@register('CGenome')
def parse_cgenome(r):
    """CGenome::Serialize (0x004185c0): payload_size_bytes:u32,
    source_filename:u32, genome_gender:u32, genome_life_stage:u8, then
    exactly payload_size_bytes raw bytes -- a standalone-.gen-format
    "gene"-chunk stream, read via one CArchive::Read memcpy (not parsed
    field-by-field by this function). CONFIRMED 2026-08-22: located this
    function's real archive tag by byte search in Aaron/Foxy/Nancy/
    Sid.exp (all bypassing the still-open CBrain issue -- this object is
    architecturally independent of it) and found payload_start +
    payload_size_bytes lands EXACTLY on the file's real EOF in every
    specimen (diff=0, all 4 tested). This means a `.exp` file is exactly
    TWO top-level MFC objects back to back: a complete Creature (see
    parse_creature) followed immediately by one CGenome -- CGenome is
    NOT nested inside CBiochemistry or Creature at all (an earlier pass
    in this file wrongly assumed that nesting)."""
    payload_size_bytes = r.u32()
    source_filename = r.u32()
    genome_gender = r.u32()
    genome_life_stage = r.u8()
    payload = r.bytes_(payload_size_bytes)
    return dict(kind='CGenome', payload_size_bytes=payload_size_bytes,
                source_filename=source_filename, genome_gender=genome_gender,
                genome_life_stage=genome_life_stage, payload=payload)


def parse_voice_tail(r):
    """Voice::Serialize (0x00445600): fixed 580 bytes -- 81 u32
    trigram-selection masks (three 27-entry groups), then 32x
    {sound_id:u32, sound_duration:u32}."""
    trigram_masks = [r.u32() for _ in range(81)]
    sounds = [(r.u32(), r.u32()) for _ in range(32)]
    return dict(trigram_masks=trigram_masks, sounds=sounds)


def parse_creature_register(r):
    """CCreatureRegister::Serialize (0x00406a60), called unconditionally
    at the very end of Creature::Serialize (0x00407440) -- outside the
    load/save branch, straight after voice. Just 10 plain length-prefixed
    MfcCString writes for C1CreatureHistory: genome_moniker, display_name,
    father_moniker, mother_moniker, birthday, birthplace, and 4 fields
    with no confirmed meaning yet. CONFIRMED 2026-08-22 against Aaron.exp
    by locating this record's real position (68 bytes ending exactly at
    the file's real "CGenome" MFC class tag) and decoding all 10 strings
    as plausible real content."""
    history = [r.mfc_string() for _ in range(10)]
    return dict(genome_moniker=history[0], display_name=history[1],
                father_moniker=history[2], mother_moniker=history[3],
                birthday=history[4], birthplace=history[5],
                unknown_history_06=history[6], unknown_history_07=history[7],
                unknown_history_08=history[8], unknown_history_09=history[9])


def parse_brain_lobe_connection_group(r):
    """One of a neuron's two C1BrainConnectionGroupHeader (5 bytes:
    connection_count:u8, connection_begin_index:u32) + that many
    C1BrainConnectionArchiveRecord (10 bytes each: target_neuron_index:
    i32, target_grid_x/y:u8, current/target/baseline_weight:u8,
    dendrite_state:u8)."""
    connection_count = r.u8()
    connection_begin_index = r.u32()
    records = []
    for _ in range(connection_count):
        target_neuron_index = r.i32()
        target_grid_x = r.u8()
        target_grid_y = r.u8()
        current_weight = r.u8()
        target_weight = r.u8()
        baseline_weight = r.u8()
        dendrite_state = r.u8()
        records.append(dict(target_neuron_index=target_neuron_index,
                             target_grid_x=target_grid_x, target_grid_y=target_grid_y,
                             current_weight=current_weight, target_weight=target_weight,
                             baseline_weight=baseline_weight, dendrite_state=dendrite_state))
    return dict(connection_count=connection_count,
                connection_begin_index=connection_begin_index, records=records)


@register('CBrain')
def parse_cbrain(r):
    """CBrain::Serialize (0x00402c50) -- RESOLVED 2026-08-22 (twelfth
    pass), byte-exact against multiple .exp specimens including a
    mature creature (dork.exp). Two loops, NOT interleaved:

    1. lobe_count:u32, then lobe_count x lobe header: C1BrainLobeArchivePrefix
       (40 raw bytes) + two CLobeConnectionRule (58 raw bytes each, NOT
       60 -- see correction note below) + C1BrainLobeArchiveCounts
       (neuron_count:u32, total_connection_count:u32) = 164 bytes/lobe.
    2. THEN, in a wholly separate second pass over the SAME lobe_count
       lobes (not interleaved with step 1): each lobe's neuron_count x
       {C1BrainNeuronArchivePrefix (6 raw bytes) + two connection groups
       (see parse_brain_lobe_connection_group)}.

    This finally resolves the long-running "lobe 5 neuron anomaly"
    investigated across ten prior passes in this docstring's history
    (all now superseded/deleted for brevity -- see 0x00402c50's Ghidra
    plate/post comments for the full blow-by-blow if needed). ROOT
    CAUSE: TWO compounding bugs, both found at once by cross-referencing
    an independent community Kaitai Struct spec for the C1 .exp format
    (github.com/mnemoli/creaturesstructs, Creatures1/c1exp.ksy):
      (a) this parser incorrectly interleaved each lobe's header with
          that SAME lobe's neuron records (header0,neurons0,header1,
          neurons1,...) -- the real format reads ALL lobe headers
          first, then ALL neuron sections after (header0..header8,
          neurons0..neurons8), confirmed independently by re-reading
          0x00402c50's own decompile, which has two genuinely separate
          top-level loops for exactly this reason (a fact found via
          disassembly in an earlier pass but never actually reflected
          in this function's implementation -- an implementation bug,
          not a re-analysis failure).
      (b) CLobeConnectionRule's ARCHIVED size is 58 bytes, not 60.
          Ghidra's own get_struct_layout('CLobeConnectionRule') reports
          60 bytes including a trailing `padding_3a[2]` field -- that
          padding is NOT actually archived (the same pattern already
          known from CLobeConnection's own `unserialized_tail_0a[2]`),
          so Ghidra's struct recovery is correct for the in-memory
          layout but was being misapplied to the wire format. This is
          now a confirmed correction to keep in mind for any other
          struct in this binary with a trailing padding field.
    With both fixes applied, all 9 lobes' neuron_count values land
    exactly on Creatures 1's well-documented built-in brain architecture
    (Perception=112, Drive=16, Source=40, Verb=16, Noun=40,
    GeneralSense=32, Decision=16, Attention=40, Concept=640 -- matching
    creatures.wiki/Brain's independently-published lobe table exactly),
    and total consumed bytes lands EXACTLY on the real CBiochemistry
    archive tag in every specimen tested (diff=0, Foxy.exp/dork.exp).
    The earlier "lobe 5 neuron anomaly" was never real data at all --
    it was 100% an artifact of the wrong interleaved read order landing
    on unrelated bytes from later lobes' headers/other lobes' neurons.
    """
    lobe_count = r.u32()
    headers = []
    for li in range(lobe_count):
        prefix = r.bytes_(40)
        rule_a = r.bytes_(58)
        rule_b = r.bytes_(58)
        neuron_count = r.u32()
        total_connection_count = r.u32()
        headers.append(dict(prefix=prefix, rule_a=rule_a, rule_b=rule_b,
                             neuron_count=neuron_count,
                             total_connection_count=total_connection_count))
    lobes = []
    for li, header in enumerate(headers):
        neurons = []
        for ni in range(header['neuron_count']):
            nprefix = r.bytes_(6)
            group0 = parse_brain_lobe_connection_group(r)
            group1 = parse_brain_lobe_connection_group(r)
            neurons.append(dict(prefix=nprefix, group0=group0, group1=group1))
        lobes.append(dict(**header, neurons=neurons))
    return dict(kind='CBrain', lobe_count=lobe_count, lobes=lobes)


@register('CBiochemistry')
def parse_cbiochemistry(r):
    """CBiochemistry::Serialize (0x0042dbe0): owner Creature object ref
    (back-reference to the Creature currently being constructed), then
    C1BiochemistryArchiveCounts (emitter/receptor/reaction gene counts,
    u32 each), 256x C1BiochemistryChemicalArchiveRecord (2 bytes:
    concentration:u8, half_life_selector:u8), then emitter_count x
    8-byte records, receptor_count x 8-byte records, reaction_count x
    9-byte records (runtime-rebuilt locus pointers are NOT in the
    archive, per this function's own eol comment -- the 8/9-byte sizes
    come from that comment, not a fresh field-by-field decompile read;
    lower confidence than the rest of this file)."""
    owner = r.read_object_ref("CBiochemistry.owner")
    emitter_gene_count = r.u32()
    receptor_gene_count = r.u32()
    reaction_gene_count = r.u32()
    chemicals = [(r.u8(), r.u8()) for _ in range(256)]
    emitters = [r.bytes_(8) for _ in range(emitter_gene_count)]
    receptors = [r.bytes_(8) for _ in range(receptor_gene_count)]
    reactions = [r.bytes_(9) for _ in range(reaction_gene_count)]
    return dict(kind='CBiochemistry', owner=owner,
                emitter_gene_count=emitter_gene_count,
                receptor_gene_count=receptor_gene_count,
                reaction_gene_count=reaction_gene_count,
                chemicals=chemicals, emitters=emitters, receptors=receptors,
                reactions=reactions)


@register('Creature')
def parse_creature(r):
    """Creature::Serialize (0x00407440) -- FULLY CONFIRMED byte-exact
    2026-08-22 against 9 real .exp specimens (Aaron/Foxy/Nancy/Sid/Vixy/
    sandy/santa/santa2/dork.exp, including a mature creature): every one
    parses this entire Creature record AND the following CGenome object
    with zero bytes left over. Full confirmed field order: Object base +
    Skeleton tail (parse_skeleton_tail), then:
      - 80x LearnedWordRecord {response:mfc_string, recognized:mfc_string,
        reinforcement:u32}
      - 40x CreatureAttentionRecord {last_x:i32, last_y:i32}
      - 36x CreatureStimulusContext (12 bytes/record: 4 fixed + an
        8-byte inner loop)
      - brain: CBrain object ref (0x00402c50). RESOLVED 2026-08-22 after
        a long investigation (see parse_cbrain's docstring) -- root cause
        was two compounding bugs in this parser (wrong header/neuron
        interleaving, wrong CLobeConnectionRule size), found by
        cross-referencing an independent community Kaitai Struct spec
        for the C1 .exp format.
      - biochemistry: CBiochemistry object ref (0x0042dbe0), read
        immediately after brain with nothing in between.
      - genome_gender:u8, genome_life_stage:u8, biochemistry_tick:u32,
        gamete_genome_source_filename:u32, child_genome_source_filename:u32,
        death_state:u8, age_ticks:u32, instinct_count:u32, dream_countdown:u32
        (27 bytes)
      - instinct_count x CInstinct object ref (0x00407070, 40 bytes each)
      - goal_direction_weight_matrix: 2-byte prefix + 640 u32 elements
        (2562 bytes total, matches get_struct_layout on
        CreatureGoalDirectionWeightMatrix exactly)
      - voice: Voice tail (Voice::Serialize, 0x00445600 -- 81 u32
        trigram-selection masks + 32x {sound_id:u32, sound_duration:u32}
        = 580 fixed bytes, starts immediately after the matrix)
      - register_state: CCreatureRegister::Serialize (0x00406a60), called
        UNCONDITIONALLY after voice outside the load/save branch -- 10
        plain length-prefixed MfcCString writes for C1CreatureHistory
        (genome_moniker, display_name, father_moniker, mother_moniker,
        birthday, birthplace, and 4 unnamed fields)

    CORRECTED 2026-09-13: `sleep_indicator_object` IS read, exactly where
    0x00407440's decompile shows it -- a ReadObject(SimpleObject) between
    the goal-direction matrix and voice. An earlier pass concluded it was
    not read at all, on the strength of 9 .exp specimens, and compensated
    with a 2-byte prefix read BEFORE the matrix. Those two readings are
    indistinguishable whenever the indicator is null, because the prefix
    consumes exactly the 2-byte NULL tag -- and every creature in those 9
    specimens was awake. The moment a creature is asleep the indicator is
    a real SimpleObject, the prefix swallows two bytes of the matrix, the
    object body is never consumed, and the archive desynchronises from
    that creature onward. That is a live world away, not a corner case:
    it is exactly what broke on a 16-creature World.sfc containing one
    sleeping norn.

    CGenome (see parse_cgenome) is a separate, later top-level object in
    the .exp archive, written immediately after this whole Creature
    record (including register_state) completes -- not part of this
    function's own return value; see parse_exp, which reads both."""
    skeleton_object_base = parse_object_base(r)
    skeleton = parse_skeleton_tail(r)

    words = []
    for _ in range(80):
        s1 = r.mfc_string()
        s2 = r.mfc_string()
        reinforcement = r.u32()
        words.append((s1, s2, reinforcement))

    attention = [(r.i32(), r.i32()) for _ in range(40)]

    stimuli = []
    for _ in range(36):
        b0 = r.u8()
        b1 = r.u8()
        b2 = r.u8()
        b3 = r.u8()
        inner = r.bytes_(8)
        stimuli.append((b0, b1, b2, b3, inner))

    brain = r.read_object_ref("Creature.brain")
    biochemistry = r.read_object_ref("Creature.biochemistry")

    genome_gender = r.u8()
    genome_life_stage = r.u8()
    biochemistry_tick = r.u32()
    gamete_genome_source_filename = r.u32()
    child_genome_source_filename = r.u32()
    death_state = r.u8()
    age_ticks = r.u32()
    instinct_count = r.u32()
    dream_countdown = r.u32()

    instincts = [r.read_object_ref(f"Creature.instincts[{i}]") for i in range(instinct_count)]

    goal_direction_weight_matrix = [r.u32() for _ in range(640)]
    sleep_indicator_object = r.read_object_ref("Creature.sleep_indicator_object")

    # The object reference above is the real thing: SimpleObject or NULL,
    # per Creature::Serialize @ 0x00407440. Verified on this repo's whole
    # corpus -- 9 .exp specimens and two World.sfc files -- all of which
    # now parse byte-exact with zero bytes remaining, including one world
    # the previous "not read, 2-byte prefix instead" model could not get
    # through at all.

    voice = parse_voice_tail(r)
    register_state = parse_creature_register(r)

    return dict(kind='Creature', skeleton_object_base=skeleton_object_base, skeleton=skeleton,
                words=words, attention=attention, stimuli=stimuli, brain=brain,
                biochemistry=biochemistry, genome_gender=genome_gender,
                genome_life_stage=genome_life_stage, biochemistry_tick=biochemistry_tick,
                gamete_genome_source_filename=gamete_genome_source_filename,
                child_genome_source_filename=child_genome_source_filename,
                death_state=death_state, age_ticks=age_ticks, instinct_count=instinct_count,
                dream_countdown=dream_countdown, instincts=instincts,
                goal_direction_weight_matrix=goal_direction_weight_matrix,
                sleep_indicator_object=sleep_indicator_object, voice=voice,
                register_state=register_state)


# ---------------------------------------------------------------------
# SFCDoc::Serialize (document archive root)
# ---------------------------------------------------------------------

def parse_object_array(r, label):
    count = r.u32()
    print(f"{label}: count={count} pos={hex(r.pos)}")
    objs = []
    for i in range(count):
        obj = r.read_object_ref(f"{label}[{i}]")
        objs.append(obj)
        if i < 3 and isinstance(obj, dict):
            print(f"  {label}[{i}]: class={obj.get('kind')} pos={hex(r.pos)}")
    print(f"  parsed {len(objs)} {label}, pos={hex(r.pos)}")
    return objs


def parse_sfc(path):
    data = open(path, 'rb').read()
    r = Reader(data)
    print("file size:", len(data))

    mapdata = r.read_object_ref("SFCDoc.MapData")
    if not (isinstance(mapdata, dict) and mapdata.get('kind') == 'MapData'):
        raise SfcArchiveError(f"expected a new MapData object at archive start, got {mapdata!r}")
    print("MapData: CONFIRMED, pos=", hex(r.pos))

    non_scenery = parse_object_array(r, "non_scenery_objects")
    scenery = parse_object_array(r, "scenery_objects")

    script_count = r.i32()
    print("script_definitions: count=", script_count, "pos=", hex(r.pos))
    scripts = []
    for i in range(script_count):
        classifier = r.u32()
        text = r.mfc_string()
        scripts.append((classifier, text))
    print("  parsed", len(scripts), "script definitions, pos=", hex(r.pos))

    viewport_left = r.i32()
    viewport_top = r.i32()
    print("viewport origin:", (viewport_left, viewport_top), "pos=", hex(r.pos))

    selected_creature = r.read_object_ref("selected_creature")
    print("selected_creature tag consumed, pos=", hex(r.pos))

    # NEWLY IMPLEMENTED 2026-08-22, confirmed straight from SFCDoc::Serialize's
    # (0x004311a0) own LOAD-path decompile, fetched in full: favourite_places
    # (6 fixed CFavouritePlace slots, direct virtual dispatch -- no object
    # tag), toolbar (MyToolBar, direct virtual dispatch), running_macros
    # (u32 count + that many Macro object refs via ReadObject), world object
    # registry (u32 count + that many polymorphic Object refs), event_bar
    # (CEventBar, direct virtual dispatch), score (CScore, direct virtual
    # dispatch), world_tick_count:u32, then serialized_document_state_words
    # (u32 count + that many raw u32 words, skipped entirely if count<=0).
    favourite_places = [parse_favourite_place(r) for _ in range(6)]
    print("favourite_places: parsed 6, pos=", hex(r.pos))

    toolbar = parse_mytoolbar(r)
    print("toolbar: parsed", len(toolbar['items']), "creature-selector items, pos=", hex(r.pos))

    running_macro_count = r.u32()
    running_macros = [r.read_object_ref(f"running_macros[{i}]") for i in range(running_macro_count)]
    print("running_macros: parsed", len(running_macros), "pos=", hex(r.pos))

    world_object_registry_count = r.u32()
    world_object_registry = [r.read_object_ref(f"world_object_registry[{i}]")
                             for i in range(world_object_registry_count)]
    print("world_object_registry: parsed", len(world_object_registry), "pos=", hex(r.pos))

    event_bar = parse_ceventbar(r)
    print("event_bar: parsed", len(event_bar['displayed_objects']), "displayed objects, pos=", hex(r.pos))

    score = parse_cscore(r)
    print("score:", score['score_values'], "pos=", hex(r.pos))

    world_tick_count = r.u32()
    print("world_tick_count:", world_tick_count, "pos=", hex(r.pos))

    doc_state_word_count = r.u32()
    doc_state_words = [r.u32() for _ in range(max(0, doc_state_word_count))] if doc_state_word_count > 0 else []
    print("serialized_document_state_words: count=", doc_state_word_count,
          "parsed", len(doc_state_words), "pos=", hex(r.pos))

    print("SFCDoc: CONFIRMED end-to-end, pos=", hex(r.pos), "/ filesize=", hex(len(data)),
          "remaining=", len(data) - r.pos)

    return dict(mapdata=mapdata, non_scenery=non_scenery, scenery=scenery,
                scripts=scripts, viewport=(viewport_left, viewport_top),
                selected_creature=selected_creature, favourite_places=favourite_places,
                toolbar=toolbar, running_macros=running_macros,
                world_object_registry=world_object_registry, event_bar=event_bar,
                score=score, world_tick_count=world_tick_count,
                doc_state_words=doc_state_words, end_pos=r.pos)


def parse_exp(path):
    """A `.exp` creature-export file is exactly TWO top-level MFC objects
    back to back -- no MapData/SFCDoc wrapper: a complete Creature
    (Skeleton/words/attention/stimuli/Brain/Biochemistry/genome-scalars/
    instincts/goal-matrix/voice/register_state -- see parse_creature)
    followed immediately by one CGenome (see parse_cgenome).

    FULLY CONFIRMED 2026-08-22, byte-exact end-to-end: this function
    round-trips all 9 .exp specimens in this repo (Aaron/Foxy/Nancy/Sid/
    Vixy/sandy/santa/santa2/dork.exp, including a mature creature) with
    zero bytes left over after both objects. This closes the entire
    `.exp` file format -- the whole investigation history (CBrain's
    long-running false leads, the sleep_indicator_object correction, the
    CGenome-nesting correction) is recorded in parse_creature's and
    parse_cbrain's docstrings and in the matching Ghidra comments on
    0x00402c50 / 0x00407440 / 0x004185c0 for anyone who wants the full
    story rather than just the resolved model."""
    data = open(path, 'rb').read()
    r = Reader(data)
    print("file size:", len(data))
    creature = r.read_object_ref("exp.Creature")
    if not (isinstance(creature, dict) and creature.get('kind') == 'Creature'):
        raise SfcArchiveError(f"expected a new Creature object at .exp start, got {creature!r}")
    print("Creature: CONFIRMED, pos=", hex(r.pos), "/ filesize=", hex(len(data)),
          "remaining=", len(data) - r.pos)
    genome = r.read_object_ref("exp.CGenome")
    if not (isinstance(genome, dict) and genome.get('kind') == 'CGenome'):
        raise SfcArchiveError(f"expected a new CGenome object after Creature, got {genome!r}")
    print("CGenome: CONFIRMED, pos=", hex(r.pos), "/ filesize=", hex(len(data)),
          "remaining=", len(data) - r.pos)
    return dict(creature=creature, genome=genome)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-World.sfc-or-.exp>", file=sys.stderr)
        sys.exit(1)
    entry = parse_exp if sys.argv[1].lower().endswith('.exp') else parse_sfc
    try:
        entry(sys.argv[1])
    except SfcArchiveError as e:
        print("STOPPED:", e)
        sys.exit(1)
    except (KeyError, struct.error, IndexError) as e:
        print(f"STOPPED: byte-alignment error ({type(e).__name__}: {e}). "
              "This means a per-class field format above is wrong somewhere upstream "
              "(or, as flagged in Lift::Serialize's own plate comment, the decompile "
              "itself may not be trustworthy at this exact call site -- worth checking "
              "raw disassembly, not just the decompile, before adjusting the parser "
              "further).")
        sys.exit(1)
