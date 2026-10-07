#!/usr/bin/env python3
"""Extract a message from the zero tail of a transition frame."""
import struct, sys

def find_zero_tail_start(pkt):
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] != 0:
            return i + 1
    return 0

def extract(infile, n_bits):
    data = open(infile, "rb").read()
    off = 0
    bits = ""
    while off + 4 <= len(data) and len(bits) < n_bits:
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4
        pkt = data[off:off+ln]
        off += ln
        start = find_zero_tail_start(pkt)
        if len(pkt) - start >= 4:
            for i in range(start, len(pkt)):
                bits += "1" if pkt[i] == 1 else "0"
                if len(bits) >= n_bits:
                    break
    # Decode bytes
    chars = []
    for i in range(0, len(bits) - 7, 8):
        chars.append(chr(int(bits[i:i+8], 2)))
    return "".join(chars)

if __name__ == "__main__":
    infile, n_bits = sys.argv[1], int(sys.argv[2])
    print(extract(infile, n_bits))