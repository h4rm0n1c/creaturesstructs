# C1 "Vivarium" DDE service

Besides the `SFC.OLE` automation object the kits use (see
[`../kit-protocol`](../kit-protocol/README.md)), Creatures 1 publishes a plain
Windows **DDEML** service named **`Vivarium`**. It runs CAOS for a client and
exposes four request items: macro output, a brain activity map, an unused
brain-wiring slot, and a line of engine counters.

No shipped C1 kit uses it -- none of the kit executables references `Vivarium`
or DDEML. It is an external debugging and tooling surface. (The string
`Vivarium` also appears in `creatures2.exe`; that service is not covered here.)

Not a file format, so no `.ksy`. Everything below is from Ghidra disassembly of
`Creatures.exe` (the CE build cited throughout this repo). There is no runnable
original binary to test against, so the live examples come from a clean-room
reimplementation built from this description, driven under Wine with
[`vivarium_client.cpp`](vivarium_client.cpp); they show the documented behaviour,
not a capture of the 1996 game.

## Registration

`InitializeDdeService @ 0x00401090`, at startup:

```
DdeInitializeA(&instance, DdeCallback, 0x00184000, 0)
    // APPCLASS_STANDARD | CBF_FAIL_ADVISES
    //                   | CBF_SKIP_REGISTRATIONS | CBF_SKIP_UNREGISTRATIONS
DdeCreateStringHandleA(instance, "Vivarium", CP_WINANSI)
DdeNameService(instance, hszVivarium, NULL, DNS_REGISTER | DNS_FILTERON)
```

then one string handle per item, in this order: `Macro`, `BrainActivity`,
`BrainWiring`, `SysInfo`. `DNS_FILTERON` means DDEML itself turns away
connections to any other service name. `ShutdownDdeService @ 0x0044edf0` is
registered with `atexit`: `DdeNameService(instance, NULL, NULL, DNS_UNREGISTER)`
(a null name unregisters everything the instance published),
`DdeFreeStringHandle` on the service name, `DdeUninitialize`.

## Transactions

All handled by `DdeCallback @ 0x0040fdb0`. Anything not listed returns 0 -- there
are no advise loops (`CBF_FAIL_ADVISES`).

| Transaction | Behaviour | Returns |
| --- | --- | --- |
| `XTYP_CONNECT` | accepted when the **service** handle is `Vivarium` and fewer than 100 conversations are open. **Any topic** is accepted. | 1 / 0 |
| `XTYP_CONNECT_CONFIRM` | creates the conversation record (below) | 0 |
| `XTYP_EXECUTE` | loads the data as the conversation's script and **starts** it | `DDE_FACK` |
| `XTYP_POKE` | loads the data as the conversation's script; **does not run it** | `DDE_FACK` |
| `XTYP_REQUEST` | calls the item's producer with the conversation's macro | data handle |
| `XTYP_DISCONNECT` | tears the conversation down (below) | 0 |

Script data from `EXECUTE` and `POKE` is read straight out of `DdeAccessData` as a
C string: it ends at the first NUL. With the debug console open and logging
enabled, `EXECUTE` also logs `DDE Execute string: "<script>"`.

### Conversations

On `XTYP_CONNECT_CONFIRM` the service allocates a 0x28-byte record holding the
conversation handle, the **topic name** (read with `DdeQueryStringA` into 32
bytes), and a fresh `Macro`:

- `script_owner` is the creature **selected at connect time**, and is never
  refreshed. (Contrast `SFC.OLE`, whose holders re-read the selection on every
  call.)
- `exec_object` is the game's initial auxiliary object; `from` is null.
- `ResetExecutionState` runs once.

The topic is then passed to `SetEmbeddedKitToolAvailabilityByName(topic, 1)`
(`0x004215f0`), which compares it case-sensitively against each `Tool<N>` ProgID
and sets that kit record's availability byte. So the convention for a client
that is a kit is to connect with its ProgID as the topic, e.g.
`DdeConnect("Vivarium", "Science.OLE")`. In this build nothing reads that byte
back; it is cleared when the Tools menu is built and written only by this
service.

On `XTYP_DISCONNECT` the record is found by handle, `DdeDisconnect` is called,
availability is cleared for a non-empty topic, the macro is removed from the
scheduler and released, and the table is compacted.

### What a request sees

Every run of a conversation's macro -- an `EXECUTE`, or a `Macro` request --
begins with `Macro::ResetExecutionState @ 0x0041a130`, which sets `targ` back to
the owner, clears `var0`..`var9`, and resets the cursors. What a script leaves
in `targ` and the variables then **persists until the next run**. That is the
channel `BrainActivity` reads through: set `targ`, `var0` and `var1` with an
`EXECUTE`, then request the item on the same conversation.

## Items

Each item record (`0x0046674c`, 12 bytes each) is `{ char *name; HSZ handle;
producer }`. Every reply is created with
`DdeCreateDataHandle(instance, buffer, cb, 0, hszItem, CF_TEXT, 0)`; what
differs is `cb`.

| Item | Producer | Reply |
| --- | --- | --- |
| `Macro` | `CreateMacroData @ 0x00410120` | the script's output |
| `BrainActivity` | `CreateBrainActivityData @ 0x004101e0` | activity map of `targ`'s brain |
| `BrainWiring` | `0x00410260` | nothing -- the producer is `xor eax,eax; ret 4` |
| `SysInfo` | `CreateSystemInfoData @ 0x00410270` | 14 engine counters |

### `Macro`

Allocates 0x4000 bytes and calls `Macro::ExecuteToOutputBuffer @ 0x0041a020`,
which resets the macro, runs the loaded script to completion capturing
`dde: putv` / `dde: puts` output, **overwrites the last output byte with NUL**,
and returns the byte count. That count is `cb`.

Every output field ends in `|`, so the final separator is the byte that becomes
the terminator:

```
POKE    "dde: putv hour,dde: putv mins"
REQUEST Macro   ->  5 bytes  "1|19\0"
```

A script that writes nothing produces `cb = 0`. If the interpreter throws, the
game shows `An exception was encountered during a DDE (iMacro) command.` and
sends zero bytes.

This is the item that runs a poked script, so `POKE` + `REQUEST Macro` is the
"run and return output" call.

### `BrainActivity`

Reads the macro's `targ` (`Macro+0xa8`, the field `new:` writes) and calls
`CBrain::FormatActivityReport @ 0x00404a90` on that creature's brain with
`var0` as the mode and `var1` as the dendrite type (0 or 1), into a 9000-byte
buffer. `cb` is the report length plus its NUL.

The report walks every lobe and neuron in order, and writes **three characters per
neuron whose value is nonzero**:

```
char 0 = '0' + lobe_x + neuron_x
char 1 = '0' + lobe_y + neuron_y
char 2 = '0' + (value >> 4)
```

`lobe_x`/`lobe_y` are the lobe's grid position (as `dde: lobe` reports) and
`neuron_x`/`neuron_y` the neuron's position inside it, so the first two
characters are absolute brain-grid coordinates offset from `'0'` -- they run
well past `'9'`. The third is the value's high nibble, `'0'`..`'?'`.

| `var0` | Value per neuron | Source |
| --- | --- | --- |
| 0 | firing strength | neuron byte 2 |
| 1 | activation | neuron byte 3 |
| 2 | largest current weight among dendrites of type `var1` | dendrite byte 6 |
| 3 | average target weight of those dendrites | dendrite byte 7 |
| 4 | average dendrite state of those dendrites | dendrite byte 9 |

(Neurons are 16-byte records: x, y, then those two bytes, then two dendrite
array pointers and two counts at +0x0c/+0x0d. Dendrites are 12 bytes. Averages are
integer division by the dendrite count, and a neuron with no dendrites of that
type is skipped.)

Live, from a creature in a fresh world:

```
EXECUTE "targ norn,setv var0 2,setv var1 0,endm"
REQUEST BrainActivity  ->  16 bytes  "e@2eD1eE0eH4eJ3\0"
```

Because connecting resets the macro once, a `BrainActivity` request straight
after `DdeConnect` reports the creature selected at connect time, in mode 0.

### `BrainWiring`

Registered, but its producer is a two-instruction stub returning null. Requests
always fail with no data.

### `SysInfo`

One `snprintf` into a 0x4000 buffer, `cb` = length + 1:

```
"%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|"
```

In order, from the argument pushes (names are this project's Ghidra labels):

| # | Source | Meaning |
| --- | --- | --- |
| 1 | `[0x004704ac]` | non-scenery objects |
| 2 | `[0x00470498]` | entities |
| 3 | `[0x004704c0]` | creatures |
| 4 | `[0x00467db0]` | installed scripts (of a fixed 2000-entry table) |
| 5 | `[0x00467dac]` | running macros |
| 6 | `[0x004721c0]` | sprite galleries |
| 7 | `[0x00468da0]` | image buffers resident in the pixel cache |
| 8 | `[0x00468da4]` | bytes in the pixel cache |
| 9 | `[map + 0x8]` | rooms |
| 10 | `[map + 0xbf0]` | map ambient environment index |
| 11 | `(signed char)[selected + 0x840]` | selected creature: action selection byte |
| 12 | `(signed char)[selected + 0x841]` | selected creature: action activation byte |
| 13 | `[selected + 0x7f0]` | selected creature: motion link (object pointer, printed as `%d`) |
| 14 | `[0x00468d90]` | smoothed idle cycle index |

Unlike every other output in this protocol, the final `|` is kept and followed
by the NUL:

```
REQUEST SysInfo  ->  49 bytes  "191|419|3|289|31|96|59|517840|26|0|0|15|0|21573|\0"
```

## Native faults

Three request paths dereference without checking:

- **An unknown item.** `FindItem` logs `DDEService::FindItem() failed` and returns
  null, and the callback calls the null record's producer. Requesting any name
  other than the four crashes the game.
- **`SysInfo` with no creature selected** reads fields 11–13 through a null
  pointer.
- **`BrainActivity` when `targ` is null or has no brain** does the same.

A client should stick to the four item names and have a creature selected.

## Under Wine

- A second `POKE`/`REQUEST` pair on one conversation can lose its reply, or
  deliver the previous one (`WDML_HandleRequestReply Positive answer should
  appear in NACK`). A minimal DDEML server with no Creatures code reproduces it.
  Use one conversation per request, or set state with `EXECUTE`, which has no
  reply to lose.
- A zero-byte reply (an empty `Macro` result) arrives as no data
  (`DMLERR_NOTPROCESSED`).

## vivarium_client.cpp

Opens one conversation, optionally `EXECUTE`s a setup script, then either
`POKE`s and `REQUEST`s one item or `EXECUTE`s a script, and prints the reply
with its exact byte count:

```
> vivarium_client SysInfo
49 bytes: "191|419|3|289|31|96|59|517840|26|0|0|15|0|21573|\0"
> vivarium_client Macro "dde: getb ovvd"
97 bytes: "Male|4b5a4633|1|0:07|N/A|47%|Healthy|7|3831|927&Female|56424d31|2|0:06|No|47%|Healthy|7|3754|927\0"
> vivarium_client --run "targ norn,setv var0 2,setv var1 1,endm" BrainActivity
--run: executed
13 bytes: "e@2eD1eH3eJ2\0"
> vivarium_client BrainWiring
no data (error 0x4009)
> vivarium_client --topic Science.OLE Macro "dde: getb cnam"
5 bytes: "Male\0"
```

```
cl /nologo /O2 /EHsc /MT vivarium_client.cpp user32.lib
i686-w64-mingw32-g++ -O2 -static vivarium_client.cpp -luser32
```
