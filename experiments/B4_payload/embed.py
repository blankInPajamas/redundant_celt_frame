#!/usr/bin/env python3
"""Embed a message into the transition frame of an Opus stream."""
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
    """Return the index of the transition frame, or -1 if none.

    The transition frame is the first frame with a large trailing-zero run
    (≥ min_tail bytes). If no such frame exists, the stream doesn't
    produce a transition.
    """
    for i, pkt in enumerate(packets):
        if trailing_zeros(pkt) >= min_tail:
            return i
    return -1

def find_tail_start(pkt):
    """Return the index where the trailing zero run starts."""
    for i in range(len(pkt) - 1, -1, -1):
        if pkt[i] != 0:
            return i + 1
    return 0

def embed(infile, outfile, message):
    msg_bytes = message.encode("ascii")
    if len(msg_bytes) > 254:
        print(f"message too long: {len(msg_bytes)} > 254")
        sys.exit(1)
    payload = bytes([len(msg_bytes)]) + msg_bytes

    data = open(infile, "rb").read()
    packets = []
    off = 0
    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4
        packets.append(bytearray(data[off:off+ln]))
        off += ln

    target = find_transition_frame(packets)
    if target < 0:
        print("no transition frame found")
        sys.exit(1)

    pkt = packets[target]
    tail_start = find_tail_start(pkt)
    tail_len = len(pkt) - tail_start

    if tail_len < len(payload):
        print(f"frame {target}: tail too short ({tail_len} < {len(payload)})")
        sys.exit(2)

    for i, b in enumerate(payload):
        pkt[tail_start + i] = b

    out = bytearray()
    for p in packets:
        out += struct.pack("<I", len(p))
        out += p

    open(outfile, "wb").write(bytes(out))
    print(f"embedded {len(payload)} bytes into frame {target} (tail_start={tail_start}, tail_len={tail_len})")

if __name__ == "__main__":
    infile, outfile, message = sys.argv[1], sys.argv[2], sys.argv[3]
    embed(infile, outfile, message)