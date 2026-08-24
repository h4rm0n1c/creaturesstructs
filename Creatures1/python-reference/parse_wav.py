#!/usr/bin/env python3
"""
Structural verifier for Creatures 1's real sound-bank .wav files (258 real
specimens under windows/Creatures/Sounds/*.wav, loaded by 4-character
filename -- the packed C1SoundId -- e.g. "vend.WAV", "cofe.wav").

Confirmed against the real engine loader, `SoundManager::LoadCachedSound`
(0x004407d0 in Creatures.exe -- already a mature, thoroughly-commented piece
of RE work from an earlier session: "Main C1 audio-format oracle... the
engine reference for kit WAV parsing"). This module mechanically replicates
that function's own chunk-read sequence exactly, rather than a generic
third-party WAV reader, so a STOPPED result here means a real specimen
doesn't fit what the real compiled loader itself expects, not just "isn't
a textbook-canonical WAV file."

Confirmed real engine expectations, read in this exact order:
    "RIFF" magic (4 bytes)
    riff_chunk_size: u32 (declared but not used to bound anything further --
             the loader trusts the inner chunk headers instead)
    "WAVE" magic (4 bytes)
    "fmt " magic (4 bytes)
    fmt_chunk_size: u32
    format_tag: u16, channel_count: u16, samples_per_second: u32,
             average_bytes_per_second: u32, block_align: u16,
             bits_per_sample: u16  (the first 16 bytes of a WAVEFORMATEX)
    if fmt_chunk_size > 16: seek forward (fmt_chunk_size - 16) bytes,
             skipping any WAVEFORMATEX extension (cbSize + extra bytes)
    next 4-byte chunk tag: if "fact" (an optional chunk some encoders emit
             for non-PCM/compressed formats), the loader unconditionally
             seeks forward 8 more bytes (the fact chunk's own 4-byte size
             field + a 4-byte sample-count payload -- a hardcoded skip, not
             a real chunk-size-driven seek) and re-reads the next 4-byte tag
    that tag must be "data"
    pcm_data_byte_size: u32
    pcm_data_byte_size raw bytes: the actual sample payload, handed directly
             to DirectSound's buffer lock/copy -- no further validation

Real engine behavior NOT modeled here (out of scope for a pure file-
structure check): the loader hardcodes `dwFlags=0xe2` and a fixed 0x24-byte
DSBUFFERDESC when creating the DirectSound buffer, and explicitly branches
on several DirectSound HRESULTs (DSERR_BUFFERLOST, DSERR_PRIOLEVELNEEDED,
DSERR_INVALIDPARAM, DSERR_INVALIDCALL) -- these are real-hardware-dependent
runtime behaviors, not properties of the file itself.
"""
import struct
import sys


class WavFormatError(Exception):
    pass


def parse_wav(path, verbose=True):
    data = open(path, 'rb').read()
    pos = 0

    def log(*a):
        if verbose:
            print(*a)

    def read(n, label):
        nonlocal pos
        if pos + n > len(data):
            raise WavFormatError(f"{label}: need {n} bytes at {hex(pos)}, only {len(data) - pos} left")
        v = data[pos:pos + n]
        pos += n
        return v

    def expect_magic(label):
        got = read(4, label).decode('latin1', errors='replace')
        if got != label:
            raise WavFormatError(f"expected {label!r} magic at {hex(pos - 4)}, got {got!r}")

    expect_magic("RIFF")
    riff_chunk_size = struct.unpack('<I', read(4, "riff_chunk_size"))[0]
    expect_magic("WAVE")
    expect_magic("fmt ")
    fmt_chunk_size = struct.unpack('<I', read(4, "fmt_chunk_size"))[0]
    format_tag, channel_count = struct.unpack('<HH', read(4, "format_tag+channel_count"))
    samples_per_second, average_bytes_per_second = struct.unpack('<II', read(8, "sample rate/byte rate"))
    block_align, bits_per_sample = struct.unpack('<HH', read(4, "block_align+bits_per_sample"))

    if fmt_chunk_size > 16:
        skip = fmt_chunk_size - 16
        log(f"  fmt chunk has {skip} extra bytes (WAVEFORMATEX extension), skipping")
        read(skip, "fmt extension")

    tag = read(4, "post-fmt chunk tag").decode('latin1', errors='replace')
    had_fact = False
    if tag == "fact":
        had_fact = True
        log("  optional 'fact' chunk present, hardcoded 8-byte skip (per real engine)")
        read(8, "fact chunk (hardcoded skip)")
        tag = read(4, "post-fact chunk tag").decode('latin1', errors='replace')

    if tag != "data":
        raise WavFormatError(f"expected 'data' chunk tag at {hex(pos - 4)}, got {tag!r}")

    pcm_data_byte_size = struct.unpack('<I', read(4, "pcm_data_byte_size"))[0]
    pcm_data = read(pcm_data_byte_size, "pcm_data")

    trailing = len(data) - pos
    log(f"RIFF size field={riff_chunk_size} (file={len(data)}), fmt_chunk_size={fmt_chunk_size}, "
        f"format_tag={format_tag}, channels={channel_count}, sample_rate={samples_per_second}, "
        f"bits_per_sample={bits_per_sample}, fact_chunk={had_fact}, pcm_bytes={pcm_data_byte_size}, "
        f"trailing={trailing}")
    log("WAV format: CONFIRMED (matches real engine loader's exact read sequence)")

    return dict(
        riff_chunk_size=riff_chunk_size, fmt_chunk_size=fmt_chunk_size,
        format_tag=format_tag, channel_count=channel_count,
        samples_per_second=samples_per_second,
        average_bytes_per_second=average_bytes_per_second,
        block_align=block_align, bits_per_sample=bits_per_sample,
        had_fact_chunk=had_fact, pcm_data_byte_size=pcm_data_byte_size,
        pcm_data=pcm_data, trailing_bytes=trailing,
    )


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-.wav-file>", file=sys.stderr)
        sys.exit(1)
    try:
        parse_wav(sys.argv[1])
    except WavFormatError as e:
        print("STOPPED:", e)
        sys.exit(1)
