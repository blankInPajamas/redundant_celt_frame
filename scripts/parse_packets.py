#!/usr/bin/env python3
import struct
import sys

def parse_packets(filename):
    with open(filename, "rb") as f:
        data = f.read()

    print(f"File: {filename}")
    print(f"Total size: {len(data)} bytes\n")

    offset = 0
    frame_idx = 0
    packets = []

    while offset + 4 <= len(data):
        pkt_len = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        if offset + pkt_len > len(data):
            print(f"Frame {frame_idx}: truncated (need {pkt_len}, have {len(data)-offset})")
            break
        packet = data[offset:offset+pkt_len]
        packets.append((frame_idx, offset, packet))
        print(f"Frame {frame_idx}: pkt_len={pkt_len}, pkt_offset={offset}, "
              f"first_bytes={packet[:8].hex()}")
        offset += pkt_len
        frame_idx += 1

    return packets

if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "data/bitstreams/encoded/test01_audio32k.bin"
    packets = parse_packets(filename)
    print(f"\nTotal packets: {len(packets)}")
