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

def find_transition_candidates(packets, min_tail=20):
    return [
        i for i, pkt in enumerate(packets)
        if trailing_zeros(pkt) >= min_tail
    ]

def find_tail_start(pkt):
    """Return the index where the trailing zero run starts."""
    for i in range(len(pkt) - 1, -1, -1):
        if pkt[i] != 0:
            return i + 1
    return 0


def embed(infile, outfile, message, target_idx=None):

    msg_bytes = message.encode("ascii")

    if len(msg_bytes) > 254:
        raise ValueError("Message too long")

    payload = bytes([len(msg_bytes)]) + msg_bytes

    data = open(infile, "rb").read()

    packets = []
    off = 0

    while off + 4 <= len(data):
        ln = struct.unpack("<I", data[off:off+4])[0]
        off += 4

        if off + ln > len(data):
            raise ValueError("Invalid packet framing")

        packets.append(bytearray(data[off:off+ln]))
        off += ln

    candidates = find_transition_candidates(packets)

    # Select the explicitly supplied index when available.
    if target_idx is None:

        if len(candidates) != 1:
            raise ValueError(
                f"Expected one candidate, found {candidates}"
            )

        target = candidates[0]

    else:

        target = int(target_idx)

        if not 0 <= target < len(packets):
            raise ValueError("Invalid target frame index")

        if target not in candidates:
            raise ValueError(
                f"Target {target} is not a verified zero-tail candidate"
            )

    pkt = packets[target]

    tail_start = find_tail_start(pkt)
    tail_len = len(pkt) - tail_start

    if tail_len < len(payload):
        raise ValueError(
            f"Frame {target}: insufficient tail capacity "
            f"({tail_len} < {len(payload)})"
        )

    # Modify only the reserved zero-filled region.
    pkt[tail_start:tail_start + len(payload)] = payload

    # Reconstruct the original packet framing.
    out = bytearray()

    for p in packets:
        out += struct.pack("<I", len(p))
        out += p

    with open(outfile, "wb") as f:
        f.write(out)

    print(
        f"embedded {len(payload)} bytes "
        f"into frame {target} "
        f"(tail_start={tail_start}, tail_len={tail_len})"
    )

if __name__ == "__main__":

    infile = sys.argv[1]
    outfile = sys.argv[2]
    message = sys.argv[3]

    target_idx = (
        int(sys.argv[4])
        if len(sys.argv) > 4
        else None
    )

    embed(infile, outfile, message, target_idx)