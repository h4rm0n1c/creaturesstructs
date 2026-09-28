# The `.egg` file format

An `.egg` file is a single Creatures 1 egg, taken out of one world so it can
be put into another. LibreCreatures makes one with **File > Export Held
Egg...** and reads it back with **File > Import Egg...**.

This is not a format from the 1996 game. The original could export and import
whole creatures (`.exp`) but never eggs. LibreCreatures defines it, and builds
it from the same parts the original uses for `.exp` files, so anything that
can read a `.exp` can read most of an `.egg`.

The formal description is [`../c1egg.ksy`](../c1egg.ksy), a Kaitai Struct spec,
and [`../c1egg.egg`](../c1egg.egg) is a real file to try it on. This page
explains the same thing in prose.

## What an egg is in Creatures 1

In a running world an egg is an ordinary object, and every egg has
classifier family 2, genus 5. The species tells kinds of egg apart: norn eggs
are 2 5 2. The world's egg scripts use three of the egg's object variables:

- `obv0` is the baby's **moniker**, the four-character name it will have.
  It is also the name of the baby's genome file, `<moniker>.gen`, in the
  world's `Genetics` folder.
- `obv1` is the **sex** the baby hatches as: 1 male, 2 female.
- `obv2` is the egg's own hatching state, used by its scripts.

The baby's genes already exist before it hatches, because the parents' genomes
are crossed at the moment the egg is made (`new: gene`). So an egg is really
three things: an egg kind, a sex, and a finished genome waiting to be born.

## What the file keeps, and what it leaves out

An `.egg` stores exactly those three things:

1. the egg's **classifier** (family, genus, species),
2. the baby's **sex**,
3. the baby's **genome**, under its **moniker**.

Everything else about a live egg is left out on purpose: its picture, how far
its hatch timer has run, its pose, and where it was lying. None of that
belongs to the egg's identity, and bringing it across would make importing
depend on the old world's layout. On import the egg starts fresh instead (see
[Importing](#importing)).

## The layout

There is no file header or magic number. Like a `.exp`, the file is an MFC
`CArchive` stream, the serialisation Microsoft's MFC library uses, and it
starts straight away with an object. It holds one object, a `CEgg`, and the
last thing inside the `CEgg` is a second object, the `CGenome` holding the
baby's genes. All numbers are little-endian.

Each object starts with a small **class record** that names what follows:

| Bytes | Meaning |
| --- | --- |
| 2 | `FF FF`: "a class seen for the first time" |
| 2 | schema number, always `01 00` |
| 2 | length of the class name |
| n | the class name, in ASCII |

After the class record come the object's own fields.

### `CEgg`

| Bytes | Field | Notes |
| --- | --- | --- |
| 4 | version | Always 1 for now. A reader should refuse any other number. |
| 4 | classifier | One byte each, in this order: event, species, genus, family. Genus must be 5 and family 2; any species is allowed. |
| 4 | sex | 1 male, 2 female. |
| ... | genome | A `CGenome` object, with its own class record. |

### `CGenome`

This is exactly the genome record a `.exp` file carries, unchanged.

| Bytes | Field | Notes |
| --- | --- | --- |
| 4 | payload size | How many genome bytes follow the header. |
| 4 | moniker | Four ASCII characters, as they appear in the filename (`0JRM` for `0JRM.gen`). |
| 4 | sex | Same as the egg's sex. |
| 1 | life stage | 0 for an unhatched baby. |
| n | payload | The genome itself, byte for byte what a `.gen` file holds: gene records starting `gene`, ending `gend`. |

The file ends right after the payload. Nothing is padded or trailing.

## A worked example

Here are the first 52 bytes of [`../c1egg.egg`](../c1egg.egg), a male norn egg:

```
00000000: ffff 0100 0400 4345 6767 0100 0000 0002  ......CEgg......
00000010: 0502 0100 0000 ffff 0100 0700 4347 656e  ............CGen
00000020: 6f6d 65ac 1e00 0030 4a52 4d01 0000 0000  ome....0JRM.....
00000030: 6765 6e65                                gene
```

Reading it byte by byte:

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | `FF FF` | new class... |
| 2 | `01 00` | ...schema 1... |
| 4 | `04 00` | ...name 4 bytes long... |
| 6 | `43 45 67 67` | ...`CEgg` |
| 10 | `01 00 00 00` | version 1 |
| 14 | `00 02 05 02` | classifier: event 0, species 2, genus 5, family 2, so a norn egg (2 5 2) |
| 18 | `01 00 00 00` | sex 1, male |
| 22 | `FF FF 01 00 07 00` | new class, schema 1, name 7 bytes long... |
| 28 | `43 47 65 6E 6F 6D 65` | ...`CGenome` |
| 35 | `AC 1E 00 00` | payload size 0x1EAC = 7,852 bytes |
| 39 | `30 4A 52 4D` | moniker `0JRM` |
| 43 | `01 00 00 00` | sex 1, male |
| 47 | `00` | life stage 0 |
| 48 | `67 65 6E 65 ...` | the genome, starting with its first `gene` |

The payload runs 7,852 bytes to offset 7,900, which is the end of the file.

## Reading and writing one

A reader needs no MFC and no Creatures code. This Python reads a file written
by LibreCreatures:

```python
import struct

def read_egg(data: bytes) -> dict:
    """Read a LibreCreatures .egg file."""
    pos = 0

    def take(fmt):
        nonlocal pos
        values = struct.unpack_from(fmt, data, pos)
        pos += struct.calcsize(fmt)
        return values

    def new_class(expected):
        nonlocal pos
        tag, schema, length = take("<HHH")
        name = data[pos:pos + length].decode("ascii")
        pos += length
        if tag != 0xFFFF or schema != 1 or name != expected:
            raise ValueError(f"expected a new {expected} record")

    new_class("CEgg")
    version, classifier, sex = take("<III")
    if version != 1:
        raise ValueError(f"unsupported .egg version {version}")
    family = classifier >> 24
    genus = (classifier >> 16) & 0xFF
    species = (classifier >> 8) & 0xFF
    if (family, genus) != (2, 5):
        raise ValueError("not an egg")

    new_class("CGenome")
    size, = take("<I")
    moniker = data[pos:pos + 4].decode("ascii")
    pos += 4
    genome_sex, life_stage = take("<IB")
    genome = data[pos:pos + size]
    pos += size
    if pos != len(data):
        raise ValueError("trailing bytes after the genome")

    return {"classifier": (family, genus, species), "sex": sex,
            "moniker": moniker, "genome_sex": genome_sex,
            "life_stage": life_stage, "genome": genome}
```

Writing one is simpler still. This makes an `.egg` from any `.gen` file, so a
tool can hand out eggs without running the game:

```python
def write_egg(genome: bytes, moniker: str, sex: int, species: int = 2) -> bytes:
    """Build a LibreCreatures .egg from a .gen file's bytes."""
    def new_class(name):
        return struct.pack("<HHH", 0xFFFF, 1, len(name)) + name.encode("ascii")

    classifier = (2 << 24) | (5 << 16) | (species << 8)
    return (new_class("CEgg")
            + struct.pack("<III", 1, classifier, sex)
            + new_class("CGenome")
            + struct.pack("<I", len(genome))
            + moniker.encode("ascii")
            + struct.pack("<IB", sex, 0)
            + genome)
```

Both have been checked against the example file: `read_egg` reads it, and
feeding what it returns back into `write_egg` rebuilds the file exactly.

A hand-made egg should use a moniker of four characters that are safe in a
filename. It doesn't have to be unique, because importing fixes clashes.

## Exporting

**Export Held Egg...** is enabled only while the hand is carrying an egg. When
you save:

1. The egg's classifier, `obv1` sex, and the genome file named by its `obv0`
   moniker are written to the file. If that genome file is missing from the
   world's `Genetics` folder, nothing is written and you're told why.
2. The egg is removed from the world, and the hand is freed.

An export moves the egg, just as exporting a creature does. The genome file
stays in the old world's `Genetics` folder.

## Importing

**Import Egg...** reads the file and:

1. **Checks the moniker.** The moniker is taken if the importing world
   already has a creature or another egg using it, or a genome file of that
   name holding different genes. If it's taken, the baby gets a new random
   moniker. Its genes don't change, but the game treats it as a separate
   individual. A genome file with the *same* genes under the same name is not
   a clash; that just means the egg has come home.
2. **Writes the genome** into the world's `Genetics` folder under the (possibly
   new) moniker.
3. **Lays a fresh egg**, the same as one from the Hatchery: full size, with one
   of the six hatchery egg pictures chosen at random, and a new hatch timer
   (2400 ticks). It is set down at spawn in the kitchen, by the incubator,
   where the Hatchery leaves its eggs, and the camera moves to show it.
4. **Deletes the file.** The egg is in the world now, so the file is used up,
   the same way importing a creature uses up its `.exp`. A file that can't be
   read is left alone.

When the egg hatches, the baby has the moniker and genes from the file (or
the new moniker, if there was a clash) and the sex the file recorded.

## Things to know

- **Any egg.** The format and the game accept any family 2 genus 5 egg, not
  just norns. An egg only hatches properly if the world it lands in has
  scripts for that kind of egg, and every standard world has them for norns.
- **Versions.** Version 1 is the only version. If a later one adds fields, they
  will come after the sex and before the genome, and older readers should
  refuse the file rather than misread it.
- **Relationship to `.exp`.** An `.exp` is a `Creature` object followed by a
  `CGenome`. An `.egg` is a `CEgg` object that contains a `CGenome`. The
  `CGenome` record is identical in both.
