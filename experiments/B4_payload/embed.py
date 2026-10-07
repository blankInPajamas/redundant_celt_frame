#!/usr/bin/env python3
"""Embed a message into the tail of a transition frame."""
import struct, sys

def find_tail_start(pkt):
    """Return the index where the trailing zero run starts."""
    for i in range(len(pkt)-1, -1, -1):
        if pkt[i] != 0:
            return i + 1
    return 0

def embed(infile, outfile, message, target_frame=3):
    msg_bytes = message.encode("ascii")
    if len(msg_bytes) > 254:
        print(f"message too long: {len(msg_bytes)} > 254")
        sys.exit(1)
    payload = bytes([len(msg_bytes)]) + msg_bytes

    data = open(infile, "rb").read()
    out = bytearray()
    off = 0
    fid = 0

    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        out += data[off:off+4]
        off += 4
        pkt = bytearray(data[off:off+ln])
        off += ln

        if fid == target_frame:
            tail_start = find_tail_start(pkt)  # ← correct start index
            tail_len = len(pkt) - tail_start

            if tail_len < len(payload):
                print(f"frame {fid}: tail too short ({tail_len} < {len(payload)})")
                sys.exit(1)

            for i, b in enumerate(payload):
                pkt[tail_start + i] = b

        out += pkt
        fid += 1

    open(outfile, "wb").write(bytes(out))
    print(f"embedded {len(payload)} bytes into frame {target_frame} (tail_start={tail_start}, tail_len={tail_len})")

if __name__ == "__main__":
    infile, outfile, message = sys.argv[1], sys.argv[2], sys.argv[3]
    target = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    embed(infile, outfile, message, target)