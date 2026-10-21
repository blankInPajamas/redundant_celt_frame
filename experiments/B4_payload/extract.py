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


def find_transition_frame(packets, tail_size=36):
    """Find the frame whose tail carries a length-prefixed printable payload.

    The modified transition frame is uniquely identifiable: byte at
    [-tail_size] is a plausible header (1..tail_size-1), and the
    following `header` bytes are printable ASCII. Content frames and
    DTX frames do not match this signature (DTX are too short; content
    frames have non-printable bytes).
    """
    for i, pkt in enumerate(packets):
        if len(pkt) < tail_size + 1:
            continue
        header = pkt[-tail_size]
        if not (1 <= header <= tail_size - 1):
            continue
        start = -tail_size + 1
        end = start + header
        if end > 0:
            continue
        payload = pkt[start:end]
        if len(payload) != header:
            continue
        if all(32 <= b < 127 for b in payload):
            return i
    return -1


def extract(infile, tail_size=36):
    packets = load_packets(infile)
    target = find_transition_frame(packets, tail_size=tail_size)
    if target < 0:
        return ""
    pkt = packets[target]
    if len(pkt) < tail_size:
        return ""
    start = len(pkt) - tail_size
    msg_len = pkt[start]
    if msg_len == 0 or msg_len + 1 + start > len(pkt):
        return ""
    msg_bytes = pkt[start + 1:start + 1 + msg_len]
    return msg_bytes.decode("ascii", errors="replace")


if __name__ == "__main__":
    infile = sys.argv[1]
    tail_size = int(sys.argv[2]) if len(sys.argv) > 2 else 36
    print(extract(infile, tail_size), end="")
