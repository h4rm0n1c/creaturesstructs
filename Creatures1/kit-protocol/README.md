# C1 kit protocol

How the Creatures 1 kits ("tools" -- Hatchery, Science Kit, Injector and the
rest) talk to the game, in both directions, with a minimal client for each.

Not a file format, so no `.ksy`. This is a live IPC protocol, recovered from
`Creatures.exe` and the kit executables and then confirmed against the running
game.

- [Game -> kit](#game---kit): one `Communicate` call, a packed header and a payload.
- [Kit -> game](#kit---game): the `SFC.OLE` automation object and its `Macro`
  conversation.
- [Launching a kit](#launching-a-kit): registration, `Tool<N>`, and the slot policy.
- [The Community Edition pipe bridge](#the-community-edition-pipe-bridge): how
  both directions cross named pipes under Wine.
- [`generic_kit.cpp`](#generic_kitcpp) and
  [`sfc_ole_client.cpp`](#sfc_ole_clientcpp): a headless kit, and a kit-side
  query client.

## Game -> kit

Every message the game sends a kit is the same call. There is only one:

```
InvokeHelper(dispatch, /*dispid*/ 1, DISPATCH_METHOD, VT_BOOL, &accepted,
             "\x4c\x4c", &header_variant, &payload_variant)
```

`"\x4c\x4c"` is two `VTS_PVARIANT`, so both arguments travel as `VARIANT*`; each
is `VT_I4`. The method is named **`Communicate`** -- a literal nowhere in the
game, which only ever asks for it by name through `GetIDsOfNames`.

The kit side declares the identical signature. Science Kit's dispatch-map entry
at `0x00412df8`: name `"Communicate"`, auto dispid, `vt` `0x0b`, params
`"\x4c\x4c"`, handler `CScienceSheet::DispatchInvoke @ 0x00409b10`.

The first argument is a packed header, the second a payload:

```
header = aux:16 | code:8 | kind:8
```

`CScienceSheet::InvokeAutomationMethod @ 0x0040bfb0` reads only the low byte --
the kind -- to choose a handler: kind 1 -> sheet vtable `+0xc8`, kind 2 ->
`+0xcc`, anything else returns TRUE and does nothing.

### Every sender in the game

| Sender | Slot | Header | Payload |
| --- | --- | --- | --- |
| `ExecuteEmbeddedKitTool @ 004444e0` (native branch) | launched | `tool<<16 \| 0x0301` | 0 |
| `SendYourIdIsMessageToEmbeddedKit @ 0042d860` (Wine branch) | launched | `tool<<16 \| 0x0301` | 0 |
| `BroadcastEmbeddedControlState @ 004449e0` | all connected | `state<<8 \| 0x02` | 0 |
| `NotifyEmbeddedKit9OfCreatureDeath @ 0040e2d0` | 9, Funeral | `0x0401` | genome filename id |
| `FlushFuneralKitDocumentStateWords @ 00435c10` | 9, Funeral | `0x0401` | queued state word |
| `NotifyDDEScoreChanged @ 0042f740` | 8, Score | `0x0401` | `&"Dummy"` |
| `SFCDoc::UpdateWorld @ 004324e0` | 8, Score | `0x0401` | `&"Dummy"` |
| `Creature::Deserialize @ 0040dda0` | 8, Score | `0x0401` | `&"Dummy"` |
| `Creature::RemoveFromWorld @ 0040e0d0` | 8, Score | `0x0401` | `&"Dummy"` |

Two kinds, two codes:

- **kind 1, code 3** -- `YOUR_ID_IS`, sent once immediately after launch. The
  slot number rides in the header's `aux` field, *not* the payload, which is 0.
- **kind 1, code 4** -- here is one integer. What it means is the receiving
  kit's business.
- **kind 2** -- control state, broadcast to every connected slot, payload 0.

`0x00458170` is the literal string `"Dummy"`. The four Score Kit senders pass its
*address* as a `VT_I4`, meaningless as an integer -- the Score Kit reads the
score itself and ignores the payload.

## Kit -> game

The game publishes one automation object, **`SFC.OLE`**
(`{77C733E1-6797-11CF-BBF2-0020AF71E433}`), served by the running game process.
A kit obtains it with `COleDispatchDriver::CreateDispatch("SFC.OLE")` and drives
it with fixed DISPIDs.

### The dispatch map

Every entry in the game's map (entry array at `0x00458398`, ten entries of 32
bytes) declares `lDispID` = `0xffffffff`, so MFC assigns DISPIDs **by position**.
The order is load-bearing -- a kit calls these by number, never by name:

| DISPID | Method | Params | Returns | Handler |
| --- | --- | --- | --- | --- |
| 1 | `RequestMacro` | `"\x4c\x4c"` (2x VTS_PVARIANT) | VT_BOOL | `0x0042fbf0` |
| 2 | `ExecuteMacro` | `"\x4c\x4c"` | VT_BOOL | `0x0042fc90` |
| 3 | `CreateMacro` | `"\x4c\x4c"` | VT_BOOL | `0x0042fa30` |
| 4 | `DestroyMacro` | `"\x4c\x4c"` | VT_BOOL | `0x0042fb00` |
| 5 | `LoadMacro` | `"\x4c\x4c"` | VT_BOOL | `0x0042fb60` |
| 6 | `CreateCommand` | `"\x02"` (VTS_I2) | VT_I4 | `0x0042fd60` |
| 7 | `DestroyCommand` | `"\x03"` (VTS_I4) | VT_BOOL | `0x0042fe30` |
| 8 | `LoadCommand` | `"\x03\x0e"` (VTS_I4 VTS_BSTR) | VT_EMPTY | `0x0042fea0` |
| 9 | `RequestCommand` | `"\x03\x48"` (VTS_I4 VTS_PBSTR) | VT_BOOL | `0x0042ffa0` |
| 10 | `FireCommand` | `"\x02\x0e\x48"` (VTS_I2 VTS_BSTR VTS_PBSTR) | VT_BOOL | `0x004300d0` |

The `*Macro` family is what the shipped kits use. Its five methods all take two
`VARIANT*`, and both directions carry data in them: the *type tag* is as
meaningful as the value.

### The conversation

    CreateMacro (3)   request  { vt = VT_I2, value = execution mode }
                      response { vt = VT_I4, value = macro holder }  <- your handle

    LoadMacro   (5)   request  { vt = VT_I4, value = handle }
                      response { vt = VT_BSTR, value = command buffer }

    RequestMacro(1)   same two, runs the script and publishes the reply

    ExecuteMacro(2)   same two, load + run + reply in one call

    DestroyMacro(4)   request  { vt = VT_I4, value = handle }

`CSfcOLE::CreateMacro @ 0x0042fa30` accepts **only** request kind 2 (`VT_I2`) and
passes `(short)value` straight to `CMacroHolder`; there is no range check.
`CSfcOLE` keeps holders in a `CObList`, so a kit must `DestroyMacro` what it
creates.

Both idioms appear in shipped kits:

- **`ExecuteMacro`** in one call -- `CScienceKitSheet::ExecuteDdeCommandWithReconnect
  @ 0x0040be90` copies the ANSI command into its buffer, then dispatches DISPID 2
  with `{VT_I4 handle}` and `{VT_BSTR buffer}`.
- **`LoadMacro` then `RequestMacro`** -- load the script once, run it and collect
  output. Observed live from the Injector: `LoadMacro caos=[dde: putv ownr]`,
  then `RequestMacro` returning 9 bytes.

### The command buffer is a real BSTR

`CScienceSheet::ConnectToCreatures @ 0x0040b870` allocates it as

    SysAllocStringByteLen(NULL, 0x1000)      // OLEAUT32 ordinal 150

-- 4096 bytes of **byte-length BSTR** storage, which the kit then writes plain
ANSI into. The length prefix is the point: it is what lets the automation
marshaller copy the buffer out to the server and the reply back. A bare `char[]`
marshals as nothing, and the call silently returns an empty reply.

`RequestMacro` does not write into your buffer. `CMacroHolder::ExecuteAndPublishMacroOutput
@ 0x00419340` runs the macro into a 16 KiB ANSI stack buffer and, when the output
is non-empty, **releases the BSTR you passed and stores a fresh one in its
place**. The answer is the VARIANT's new `bstrVal` -- which is exactly why
`CKitSheet` caches the returned pointer rather than re-reading its own buffer.

### Execution modes

`CMacroHolder::CMacroHolder @ 0x004191b0` installs a five-entry callback table,
indexed by the mode handed to `CreateMacro`:

| Mode | Dispatch callback | Meaning |
| --- | --- | --- |
| 0 | `StartMacroExecution` | queue on the world scheduler; no output |
| 1 | `ExecuteMacroToOutputBuffer` | run to completion now and publish output |
| 2 | `FormatBrainActivityReport` | brain activity report |
| 3, 4 | `SetZeroCallbackResult` | accepted, return zero |

Mode 0 is what an installer script wants (`wait`, `anim` and friends span ticks);
mode 1 is what a query wants. Anything above 4 indexes off the end of the table.

`CMacroHolder::InvokeDispatchEntry @ 0x004192d0` refreshes
`Macro.object_context.script_owner` from `g_selected_creature` **on every
dispatch**. So a kit's script always runs owned by whatever creature is selected
in the game, which is why `putv gend`, `putv chem N` and `getb cnam/monk/data`
describe the selection without the kit naming it.

### What comes back

Output is written by `dde: putv <value>` and `dde: puts [text]` only. C1 strings
are bracketed; `outv`/`outs` are Creatures 2 commands and write nothing at all.

Each field is terminated with `|`, and the game overwrites the final separator
with a NUL -- so a reply is `field|field|field\0`, not a trailing-pipe list.
`getb ovvd` adds a second level: one record per creature, records separated by
`&`. `dde: getb` *replaces* the output buffer rather than appending, so a request
carrying two `getb`s returns only the last one.

### CAOS the kits send

Kits drive the game with ordinary CAOS. Scripts that change the world are wrapped
`inst,<body>,endm`; plain queries are sent bare. Both shapes, live from the
Injector:

```
dde: putv ownr                                        (query, bare)
dde: getb cnam                                        (query, bare)
inst,new: simp cbox 2 0 9000 0,setv clas 33754624,…,endm   (installer)
inst,app: quit %d,endm                                (every kit, on exit)
```

The game's `dde:` dispatcher accepts 16 verbs, several with their own
sub-vocabulary:

| Group | Verbs |
| --- | --- |
| Query bytes | `getb monk` `data` `ovvd` `cnam` `ctim` |
| Query ids | `gids root` `fmly` `gnus` `spcs` |
| Push value | `putv` (`ownr` `norn` `gend` `chem N` `scor N` `mins` `hour` `_it_`) |
| Push other | `puts` `putb` |
| Events | `live` `died` `negg` `hatc` |
| Inspect | `lobe` `gene` `word` `cell` |
| Misc | `scrp` `pict` `panc` |

`dde: lobe` answers in **binary**, not text: one count byte, then five bytes per
lobe (`x`, `y`, `width`, `height` in brain-grid cells, and a flag), read from
`CLobe` offsets 4/8/12/16/34, then a `0xff` terminator. For a standard norn that
is 54 bytes.

Kits also use ordinary non-`dde:` CAOS -- `new: simp/scen/crea/gene/…`,
`stim from/shou/sign/tact/writ`, `setv`, and `app: quit`.

### What each kit sends

| Kit | Repertoire |
| --- | --- |
| Hatchery | `dde: hatc`, `new: gene`, `new: simp eggs`, `setv obv1/attr/clas` |
| Science Kit | `dde: putv chem N`, `cell`, `gene`, `putv gend/_it_`, `getb cnam/monk` |
| Health Kit | `dde: putv chem N`, `lobe`, `getb cnam`, `setv var0` |
| Breeder's Kit | `dde: putv chem N` (batches), `putv gend`, `getb cnam/monk` |
| Owner's Kit | `dde: pict`, `panc`, `getb cnam/ctim/data/monk`, `putb [%s] data`, `putv gend` |
| Score Kit | `dde: putv scor N`, `putv mins`, `putv hour`, `getb cnam` |
| Funeral Kit | `dde: putv ownr`, `getb cnam` |
| observation | `dde: getb ovvd` |
| BiochemKit † | `dde: putv chem N`, `getb cnam`, `chem %d %d` |
| Injector † | the full set -- all `gids`, all `getb`, all `new:`, all `stim` |

† `BiochemKit.exe` and `Injector.exe` link `mfc140.dll` and carry 2020s PDB
paths: they are Community Edition rebuilds, not 1996 kits. They speak the same
protocol -- everything above was observed live from the Injector -- but cite the
MFC40 kits when the question is what the original game shipped.

### When connecting fails

`CKitSheet::ConnectToCreatures` reports a failed `CreateDispatch` through
`CException::ReportError`, and falls back to its own message box only when
ReportError has nothing to say. So a kit that cannot reach the game shows MFC's

    No error message is available.

and **not** "Cannot communicate with Creatures". That dialog means the SFC.OLE
registration is wrong or the game is not running -- see registration below.

## Launching a kit

The game resolves the ProgID to an executable through
`CLSID\{…}\LocalServer32`, then launches it with **named switches, not
positional arguments**:

```
YourKit.exe /Embedding /ToolID=6 /ProgID=Your.OLE
```

Reading `argv[1]` positionally makes a kit serve slot 0 while the game talks to
slot 6 -- silent, and looks exactly like a dead connection.

### Registration

What the shipped `regs.cmd` writes, per server. Everything under `Classes` goes
into the **32-bit view** (`/reg:32`, i.e. `Wow6432Node` on 64-bit Windows and
Wine); a key written to the 64-bit view is invisible to the game and its kits.

```
HKLM\SOFTWARE\Classes\<ProgID>                               -> "<ProgID>"
HKLM\SOFTWARE\Classes\<ProgID>\CLSID                         -> {CLSID}
HKLM\SOFTWARE\Classes\CLSID\{CLSID}                          -> "<ProgID>"
HKLM\SOFTWARE\Classes\CLSID\{CLSID}\InprocHandler32          -> ole32.dll
HKLM\SOFTWARE\Classes\CLSID\{CLSID}\LocalServer32            -> path to exe
HKLM\SOFTWARE\Classes\CLSID\{CLSID}\ProgID                   -> "<ProgID>"
HKCU\Software\Gameware Development\Creatures 1\1.0\Tool<N>   -> "<ProgID>|name|help|<N>"
```

`SFC.OLE` itself is registered the same way, with `LocalServer32` naming the
game executable. A kit's `CreateDispatch` goes through that key, so if it names a
stale path the kit cannot connect, even with the game running.

The shipped registrations:

| Server | ProgID | CLSID | Executable |
| --- | --- | --- | --- |
| game | `SFC.OLE` | `{77C733E1-6797-11CF-BBF2-0020AF71E433}` | `Creatures.exe` |
| game document | `Creatures.Document` | `{380459A0-3587-11CF-94B8-444553540000}` | `Creatures.exe` |
| Tool0 | `Hatchery.OLE` | `{F10D5CA1-A8B7-11CF-BBF2-0020AF71E433}` | `Hatchery.exe` |
| Tool2 | `Owner.OLE` | `{4388EF01-A35C-11CF-BBF2-0020AF71E433}` | `Owner's Kit.exe` |
| Tool3 | `Health.OLE` | `{7CCFFEC1-A43D-11CF-BBF2-0020AF71E433}` | `Health Kit.exe` |
| Tool4 | `Science.OLE` | `{D7885C00-9F7D-11CF-BBF2-0020AF71E433}` | `Science Kit.exe` |
| Tool5 | `Sex.OLE` | `{B4A467E1-AF33-11CF-BBF2-0020AF71E433}` | `Breeder's Kit.exe` |
| Tool6 | `OVERVIEW.OLE` | `{82720CE1-C6E4-11D0-A8BB-00A0C9008A48}` | `observation.exe` |
| Tool7 | `ObjectInjector.OLE` | `{B07C9809-2CE6-11D0-AB39-0020AF71E433}` | `Injector.exe` |
| Tool8 | `Score.OLE` | `{3DC4BDA1-B95B-11CF-BBF2-0020AF71E433}` | `Score Kit.exe` |
| Tool9 | `Funeral.OLE` | `{D3BCF121-A4D8-11CF-BBF2-0020AF71E433}` | `Funeral Kit.exe` |

**Tool1 is deliberately absent** -- nine kits, not ten. (The shipped `regs.cmd`
also has a copy-paste slip: its `Sex.OLE` block writes `InprocHandler32`,
`LocalServer32` and `ProgID` under the Injector's CLSID `{B07C9809-…}` instead of
`{B4A467E1-…}`, so run as written it points the Injector's CLSID at
`Breeder's Kit.exe`. Registering the Breeder's Kit under its own CLSID is the
evident intent.)

### `Tool<N>` values

`<ProgID>|<menu name>|<help text>|<slot digit>`. The third field is status-bar
help text, not a launch command. The fourth is the slot as an ASCII digit, which
also selects the toolbar image (`digit - 0x30`).

Two writers disagree on the value type: an installer writes **REG_SZ**, while the
CAOS `tool` command writes **REG_BINARY** (it passes type 3 to `RegSetValueEx`).
The game's reader, `PopulateEmbeddedKitMenuAndToolbarFromRegistry @ 0x004440e0`,
reads the type into a local and never tests it, so both load. A reimplementation
that insists on one type comes up with an empty Tools menu against a real
install.

### The slot number is policy

`CMainFrame::OnUpdateEmbeddedKitToolCommand @ 0x004216d0` enables a Tools menu
entry by **slot index**, not by which kit is there:

| Slot | Enabled when |
| --- | --- |
| 0 | world running, and fewer creatures in the world than `MaxNorns` |
| 6, 8, 9 | world running |
| 7 | world running alone if `HKCU\SOFTWARE\Gameware Development\Creatures\Injector Kit\2.0\AllowWithoutSubject` is nonzero; otherwise as "any other" |
| any other | world running and the selected creature alive |

Before any of that, a kit that is not already running is disabled once the number
of running kits reaches `MaxKits` (read from the game's `1.0` key; written as 4 if
absent).

Slot 7 is hard-wired to the Injector's own registry key. Ghidra's decompiler drops
that branch entirely and shows the value read but never used; the disassembly
at `0x0042183b` tests it and, when set, enables on `SETZ` of the world timer
state alone.

That is why the canonical order matters: the Hatchery belongs in 0, and the
Observation, Performance and Graveyard kits -- which need no creature -- in 6, 8
and 9.

## The Community Edition pipe bridge

Under Wine the CE build (the 550,400-byte `Creatures.exe` cited throughout) takes
a second launch branch and bridges both directions over named pipes. The 1996 retail binary has only the native COM
branch; `Communicate` and the `SFC.OLE` methods are unchanged either way.

The bridge is `OLEKitProxy.dll`, which ships beside the game. The game loads it
and calls `LaunchKitWithInjection(exePath, toolID, progID)`; that starts
`"<kit>" /Embedding /ToolID=<N> /ProgID=<ProgID>` and injects the same DLL into
the kit. Inside the kit it inline-hooks `CoRegisterClassObject` (to capture the
kit's class factory and `IDispatch`), `CoRevokeClassObject` and `DestroyWindow`
(to notice the kit closing).

### Registration the bridge needs

`OLEKitProxy.dll`'s `DllRegisterServer` files it as

```
HKCR\CLSID\{77C733E1-6797-11CF-BBF2-0020AF71E433}\InprocServer32 -> OLEKitProxy.dll
                                                  ThreadingModel -> Apartment
```

-- `SFC.OLE`'s own CLSID. A kit's `CreateDispatch("SFC.OLE")` therefore loads an
in-process `CSfcOLEProxy` instead of reaching for the game, and that proxy
forwards each call over the pipe. **Without this key no kit connects under
Wine**, and each one shows the empty-exception dialog described above.
`regsvr32 OLEKitProxy.dll` writes it; anything that later rewrites the `SFC.OLE`
CLSID must leave it in place.

### Game -> kit: `\\.\pipe\Creatures1_Kit_Tool<N>`

The injected DLL serves this pipe inside the kit. Each `Communicate` becomes one
connection carrying exactly **8 bytes**: the header dword, then the payload dword,
little-endian, in source order. The proxy posts them to a hidden marshal window
on the kit's main thread, which calls the kit's real `IDispatch` --
`GetIDsOfNames("Communicate")`, then `Invoke`. There is no reply; the game treats
a successful write as acceptance.

### Kit -> game: `\\.\pipe\SFC_OLE`

The game serves this pipe. Each request is text:

```
<VERB> 0x1E <arg1> [0x1E <arg2>] 0x00
```

Replies have the same shape -- `OK[0x1E…]` or `ERROR 0x1E <detail>` -- and are
also NUL-terminated.

| Verb | Arguments | Reply |
| --- | --- | --- |
| `CREATEMACRO` | execution mode | `OK <handle>` |
| `LOADMACRO` | handle, script | `OK` |
| `REQUESTMACRO` | handle | `OK <byte count> <output>` |
| `EXECUTEMACRO` | handle, script | `OK` |
| `DESTROYMACRO` | handle | `OK` |
| `FIRECOMMAND` | execution mode, script | `OK <byte count> <output>` |
| `KITQUIT` | tool slot | `OK Kit cleaned up` |

`FIRECOMMAND` is create, load, run and destroy in one request, and the easiest
way to inject CAOS from a test tool. `KITQUIT` is what the injected DLL sends when
it sees the kit's last top-level window close, so the game frees the slot.

**The terminating NUL is part of the message.** The proxy writes it, and a server
that treats it as content will fail every numeric argument -- `"0\0"` does not
parse as 0. A reimplementation of this pipe must strip trailing NULs before
splitting on `0x1E`. (Found the hard way: a kit's `CREATEMACRO` was rejected as
`Type out of range` while the byte-identical request without the terminator
succeeded.)

### Debugging the bridge

Set

```
HKCU\Software\Gameware Development\Creatures 1\1.0\EnableOLELogging = 1
```

and every process that loads `OLEKitProxy.dll` appends to
`%TEMP%\OLEKitProxy_Debug.log`: hook installation, pipe connects, each posted
`Communicate`, and every forwarded macro call with its CAOS and result, e.g.

```
CoRegisterClassObject: Captured class factory 0x00419ACC for kit!
PipeThread: Posting message v1=0x00070301, v2=0x00000000
CreateMacro: type=1, handle=44282920
LoadMacro: handle=44282920, success=1, caos=[dde: putv ownr]
RequestMacro: handle=44282920, success=1, dataLen=9
```

It is the fastest way to tell "the game never sent it" from "the kit never asked".

## generic_kit.cpp

A kit that does nothing but report. It accepts every method name asked of it,
logs it, and logs every `Invoke` with arguments decoded in source order. Launch
it from the game's Tools menu and it writes:

```
GetIDsOfNames: "Communicate" -> dispid 1
Invoke: dispid=1 flags=0x0001 args=2
    arg0: VT_I4 393985
    arg1: VT_I4 0
```

`393985` is `0x00060301`: kind 1, code 3, aux 6 -- `YOUR_ID_IS` for tool slot 6.

```
cl /nologo /O2 /EHsc /MT generic_kit.cpp user32.lib ole32.lib oleaut32.lib
```

## sfc_ole_client.cpp

The other direction: a command-line kit that connects to the running game's
`SFC.OLE` the way the shipped kits do -- `CreateMacro` in mode 1, `LoadMacro`,
`RequestMacro`, `DestroyMacro`, over a byte-length BSTR buffer -- runs one CAOS
query and prints the reply:

```
> sfc_ole_client "dde: putv totl 0 0 0"
191
> sfc_ole_client "dde: getb cnam"
Male
> sfc_ole_client "dde: putv hour,dde: putv mins"
0|58
```

Build it 32-bit:

```
cl /nologo /O2 /EHsc /MT sfc_ole_client.cpp ole32.lib oleaut32.lib
i686-w64-mingw32-g++ -O2 -static sfc_ole_client.cpp -lole32 -loleaut32 -luuid
```

Between them, `generic_kit.cpp` and `sfc_ole_client.cpp` are a complete kit's
worth of protocol with no MFC.

## Provenance

Addresses in `Creatures.exe` are in the Creatures Exodus/CE build (550,400
bytes, MSVC linker 14.44). Kit addresses are in the shipped kit executables.
Everything was read from Ghidra disassembly, then confirmed live under Wine:

- **Game -> kit**: `generic_kit.cpp` registered in slot 6 received exactly the
  recovered encoding.
- **Kit -> game**: `sfc_ole_client.cpp` drove the `Macro` conversation against the
  running game, through `OLEKitProxy.dll`'s in-process proxy and the `SFC_OLE`
  pipe.
- **A real kit end to end**: the Injector, with `EnableOLELogging` set, connected,
  named the selected creature, listed and analysed COBs, and injected one -- the
  game's object count rose by one and the object appeared in the world.

Kit citations for the original protocol come from the MFC40 kits (Science Kit,
Health Kit, Owner's Kit and the rest). `Injector.exe` and `BiochemKit.exe` are
mfc140 Community Edition rebuilds; they are cited only for what they themselves
do.

Cautions for anyone re-deriving this:

- **Ghidra mis-renders `COleDispatchDriver::InvokeHelper`.** It swallows the
  `self` argument and shifts the rest left, so the real
  `InvokeHelper(self, 1, 1, 0xb, pvRet, "LL", &v0, &v1)` prints as
  `InvokeHelper(3, 1, VT_I4, pvRet, "\x0b")` -- wrong DISPID, wrong return type,
  and the `vtRet` push mistaken for the parameter-info string. Read the pushes.
- **Ghidra also drops branches.** `OnUpdateEmbeddedKitToolCommand`'s
  `AllowWithoutSubject` test is absent from its decompile; see the slot table.
- **Read the VARIANT tags.** The `SFC.OLE` methods carry meaning in the `vt`
  field as well as the value: `CreateMacro` refuses any request not tagged
  `VT_I2`.
