#!/usr/bin/env python3
"""Embed a message into the zero tail of a transition frame."""
import struct, sys

def find_zero_tail(pkt):
    tail = 0
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] == 0:
            tail += 1
        else:
            break
    return tail

def embed(infile, outfile, message_bits):
    data = open(infile, "rb").read()
    out = bytearray()
    off = 0
    bit_idx = 0
    frame_idx = 0
    embedded = 0

    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        out += data[off:off+4]
        off += 4
        pkt = bytearray(data[off:off+ln])
        off += ln

        tail = find_zero_tail(pkt)
        if tail >= 4 and bit_idx < len(message_bits):
            start = len(pkt) - tail
            for i in range(start, len(pkt)):
                if bit_idx >= len(message_bits):
                    break
                pkt[i] = 1 if message_bits[bit_idx] == "1" else 0
                bit_idx += 1
                embedded += 1

        out += pkt
        frame_idx += 1

    open(outfile, "wb").write(bytes(out))
    print(f"embedded {embedded} bits across {frame_idx} frames")

if __name__ == "__main__":
    infile, outfile, message = sys.argv[1], sys.argv[2], sys.argv[3]
    bits = "".join(f"{ord(c):08b}" for c in message)
    embed(infile, outfile, bits)