#!/usr/bin/env python3
"""Extract a message from the transition frame's tail."""
import struct, sys


def load_packets(path):
    data = open(path, "rb").read()
    packets = []
    off = 0
    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4
        packets.append(data[off:off+ln])
        off += ln
    return packets


def find_transition_frame(packets, min_size=80):
    """Locate the transition frame as the first frame with size >= min_size.

    The transition frame is the first packet that exceeds steady-state DTX
    size (3 bytes), because it carries both the mode-switch signal and the
    redundant-frame reservation. This signature is invariant under in-place
    payload modification (packet sizes do not change).
    """
    for i, pkt in enumerate(packets):
        if len(pkt) >= min_size:
            return i
    return -1


def extract(infile, tail_size=36):
    packets = load_packets(infile)
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