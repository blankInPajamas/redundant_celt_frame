#!/usr/bin/env python3
"""Extract a message from the transition frame's tail."""
import struct, sys

def trailing_zeros(pkt):
    """Count trailing zero bytes in a packet."""
    t = 0
    for i in range(len(pkt) - 1, -1, -1):
        if pkt[i] == 0:
            t += 1
        else:
            break
    return t

def find_transition_frame(packets, min_tail=20):
    """Find the transition frame.

    For clean streams, the tail is all zeros. For stego streams, the tail
    contains payload bytes. We use the size heuristic as the identifier.
    """
    # First try: look for a frame with a large trailing-zero run.
    for i, pkt in enumerate(packets):
        if trailing_zeros(pkt) >= min_tail:
            return i

    # Fallback: use size heuristic.
    for i, pkt in enumerate(packets):
        if len(pkt) >= 80:
            return i
    return -1

def extract(infile, tail_size=36):
    data = open(infile, "rb").read()
    packets = []
    off = 0
    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4
        packets.append(data[off:off+ln])
        off += ln

    target = find_transition_frame(packets)
    if target < 0:
        return ""

    pkt = packets[target]
    if len(pkt) < tail_size:
        return ""

    start = len(pkt) - tail_size
    msg_len = pkt[start]
    if msg_len == 0 or msg_len + 1 + start > len(pkt):
        return ""
    msg_bytes = pkt[start+1 : start+1+msg_len]
    return msg_bytes.decode("ascii", errors="replace")

if __name__ == "__main__":
    infile = sys.argv[1]
    tail_size = int(sys.argv[2]) if len(sys.argv) > 2 else 36
    print(extract(infile, tail_size), end="")