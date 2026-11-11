#!/usr/bin/env python3

"""Strict extractor for B4's dynamically positioned zero-tail payload."""

import struct
import sys
from pathlib import Path


def load_packets(path):
    data = Path(path).read_bytes()
    packets = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("Incomplete packet-length header")

        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        if length == 0 or offset + length > len(data):
            raise ValueError("Invalid or truncated packet")

        packets.append(data[offset:offset + length])
        offset += length

    return packets


def find_payloads(packets):

    hits = []

    for packet_index, packet in enumerate(packets):

        for pos in range(len(packet)):

            # The embedding starts immediately after a nonzero byte.
            if pos > 0 and packet[pos - 1] == 0:
                continue

            message_length = packet[pos]

            if not 1 <= message_length <= 254:
                continue

            end = pos + 1 + message_length

            if end >= len(packet):
                continue

            payload = packet[pos + 1:end]
            padding = packet[end:]

            printable = all(32 <= b < 127 for b in payload)
            zero_padding = all(b == 0 for b in padding)

            if printable and padding and zero_padding:

                hits.append({
                    "packet": packet_index,
                    "offset": pos,
                    "message": payload,
                    "padding": len(padding)
                })

    return hits


def main():

    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: extract_verified.py input.bin"
        )

    packets = load_packets(sys.argv[1])
    hits = find_payloads(packets)

    if len(hits) != 1:
        raise SystemExit(
            f"Extraction failed: expected 1 payload, found {len(hits)}"
        )

    hit = hits[0]

    print(
        f"Recovered packet={hit['packet']} "
        f"offset={hit['offset']} "
        f"padding={hit['padding']} bytes",
        file=sys.stderr
    )

    sys.stdout.buffer.write(hit["message"])


if __name__ == "__main__":
    main()
