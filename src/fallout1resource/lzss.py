"""Fallout DAT1 block LZSS decompression with strict output bounds."""

from __future__ import annotations


DICTIONARY_SIZE = 4096
MIN_MATCH = 3
MAX_MATCH = 18


class LzssError(ValueError):
    """Raised when a DAT1 LZSS stream is malformed or exceeds its declared size."""


def decompress_lzss_block(data: bytes, *, max_output: int) -> bytes:
    if max_output < 0:
        raise LzssError("negative output limit")
    dictionary = bytearray(b" " * DICTIONARY_SIZE)
    dictionary_index = DICTIONARY_SIZE - MAX_MATCH
    output = bytearray()
    cursor = 0
    flags = 0

    while cursor < len(data):
        flags >>= 1
        if flags & 0x0100 == 0:
            flags = data[cursor] | 0xFF00
            cursor += 1
            if cursor == len(data):
                raise LzssError("flag byte has no following token")

        if flags & 1:
            if len(output) >= max_output:
                raise LzssError("LZSS output exceeds declared file size")
            value = data[cursor]
            cursor += 1
            output.append(value)
            dictionary[dictionary_index % DICTIONARY_SIZE] = value
            dictionary_index += 1
        else:
            if cursor + 2 > len(data):
                raise LzssError("truncated LZSS dictionary token")
            dictionary_offset = data[cursor] | ((data[cursor + 1] & 0xF0) << 4)
            length = (data[cursor + 1] & 0x0F) + MIN_MATCH
            cursor += 2
            if len(output) + length > max_output:
                raise LzssError("LZSS output exceeds declared file size")
            for index in range(length):
                value = dictionary[(dictionary_offset + index) % DICTIONARY_SIZE]
                output.append(value)
                dictionary[dictionary_index % DICTIONARY_SIZE] = value
                dictionary_index += 1

    return bytes(output)

def decompress_dat1_payload(packed: bytes, *, expected_size: int) -> bytes:
    """Decompress a DAT1 0x40 payload made of signed-size LZSS blocks."""
    if expected_size < 0:
        raise LzssError("negative expected size")
    output = bytearray()
    cursor = 0

    while cursor < len(packed):
        if cursor + 2 > len(packed):
            raise LzssError("truncated DAT1 block header")
        declared_size = int.from_bytes(packed[cursor : cursor + 2], "big", signed=True)
        cursor += 2
        if declared_size == 0:
            raise LzssError("zero-sized DAT1 block")

        remaining = len(packed) - cursor
        block_size = min(abs(declared_size), remaining)
        if block_size == 0:
            raise LzssError("DAT1 block has no data")
        block = packed[cursor : cursor + block_size]
        cursor += block_size
        remaining_output = expected_size - len(output)
        if remaining_output < 0:
            raise LzssError("output exceeds declared file size")

        if declared_size < 0:
            if len(block) > remaining_output:
                raise LzssError("uncompressed block exceeds declared file size")
            output.extend(block)
        else:
            output.extend(decompress_lzss_block(block, max_output=remaining_output))

    if len(output) != expected_size:
        raise LzssError(f"decompressed size mismatch: got {len(output)}, expected {expected_size}")
    return bytes(output)
