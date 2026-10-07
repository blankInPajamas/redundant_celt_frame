#!/usr/bin/env python3
"""Extract a message from the tail of a transition frame."""
import struct, sys

def extract(infile, target_frame=3, tail_size=36):
    data = open(infile, "rb").read()
    off = 0
    fid = 0

    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4
        pkt = data[off:off+ln]
        off += ln

        if fid == target_frame:
            if len(pkt) < tail_size:
                return ""
            start = len(pkt) - tail_size
            msg_len = pkt[start]
            if msg_len == 0 or msg_len + 1 + start > len(pkt):
                return ""
            msg_bytes = pkt[start+1 : start+1+msg_len]
            return msg_bytes.decode("ascii", errors="replace")
        fid += 1

    return ""

if __name__ == "__main__":
    infile = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    tail_size = int(sys.argv[3]) if len(sys.argv) > 3 else 36
    print(extract(infile, target, tail_size), end="")