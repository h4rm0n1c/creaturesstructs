# C1 kit protocol

How the Creatures 1 kits ("tools" -- Hatchery, Science Kit, Injector and the
rest) talk to the game, and a headless kit that speaks it.

Not a file format, so no `.ksy`. This is a live IPC protocol, recovered from
`Creatures.exe` and the kit executables and then confirmed against the running
game.

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

Kits drive the game with CAOS macros, always shaped `inst,<body>,endm`, sent
through the game's automation object. Bodies are `dde:` subcommands:

```
inst,dde: putv chem 66,dde: putv chem 59,endm      (Breeder's Kit)
inst,dde: getb ovvd,endm                           (observation)
inst,app: quit %d,endm                             (every kit, on exit)
```

The game's dispatcher accepts 21 `dde:` verbs:

| Group | Verbs |
| --- | --- |
| Query bytes | `getb monk` `data` `ovvd` `cnam` `ctim` |
| Query ids | `gids root` `fmly` `gnus` `spcs` |
| Push value | `putv` (`ownr` `norn` `gend` `chem N` `scor N` `mins` `hour` `_it_`) |
| Push other | `puts` `putb` |
| Events | `live` `died` `negg` `hatc` |
| Inspect | `lobe` `gene` `word` `cell` |
| Misc | `scrp` `pict` `panc` |

Kits also use ordinary CAOS outside `dde:` -- `new: simp/scen/crea/gene/…`,
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
| BiochemKit | `dde: putv chem N`, `getb cnam`, `chem %d %d` |
| Injector | the full set -- all `gids`, all `getb`, all `new:`, all `stim` |

Every kit also sends `inst,app: quit %d,endm` when closed.

## Launching a kit

The game resolves the ProgID to an executable through
`CLSID\{…}\LocalServer32`, then launches it with **named switches, not
positional arguments**:

```
YourKit.exe /Embedding /ToolID=6 /ProgID=Your.OLE
```

Reading `argv[1]` positionally makes a kit serve slot 0 while the game talks to
slot 6 -- silent, and looks exactly like a dead connection.

Registration:

```
HKCR\<ProgID>\CLSID                                          -> {CLSID}
HKCR\CLSID\{CLSID}\LocalServer32                             -> path to exe
HKCU\Software\Gameware Development\Creatures 1\1.0\Tool<N>   -> "<ProgID>|name|help|<N>"
```

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

## Provenance

Addresses above are in the Creatures Exodus/CE build of `Creatures.exe`
(550,400 bytes, MSVC linker 14.44) and in the shipped kit executables, read from
Ghidra disassembly. The protocol was then confirmed live: the game was run under
Wine with `generic_kit.cpp` registered in slot 6, and the message it received
matched the recovered encoding exactly.

Two cautions for anyone re-deriving this:

- **Ghidra mis-renders `COleDispatchDriver::InvokeHelper`.** It swallows the
  `self` argument and shifts the rest left, so the real
  `InvokeHelper(self, 1, 1, 0xb, pvRet, "LL", &v0, &v1)` prints as
  `InvokeHelper(3, 1, VT_I4, pvRet, "\x0b")` -- wrong DISPID, wrong return type,
  and the `vtRet` push mistaken for the parameter-info string. Read the pushes.
- **The Wine branch is CE-specific.** That build loads `OLEKitProxy.dll` and
  calls `LaunchKitWithInjection`, which launches the kit and injects itself to
  bridge COM over named pipes. The 1996 retail binary has only the native COM
  branch. The `Communicate` protocol is identical either way. Details in
  `generic_kit.cpp`'s header comment.
