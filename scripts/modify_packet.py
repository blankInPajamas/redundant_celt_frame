#!/usr/bin/env python3
import struct
import sys

def modify_packet(infile, outfile, frame_idx, byte_offset, new_value=None):
    with open(infile, "rb") as f:
        data = f.read()

    offset = 0
    current_frame = 0
    out = bytearray()

    while offset + 4 <= len(data):
        pkt_len = struct.unpack("<I", data[offset:offset+4])[0]
        header = data[offset:offset+4]
        offset += 4
        packet = bytearray(data[offset:offset+pkt_len])

        if current_frame == frame_idx:
            if byte_offset < len(packet):
                old = packet[byte_offset]
                if new_value is None:
                    new_value = old ^ 0xFF
                packet[byte_offset] = new_value
                print(f"Frame {frame_idx}: modified byte {byte_offset}: "
                      f"0x{old:02x} -> 0x{new_value:02x}")
            else:
                print(f"Frame {frame_idx}: byte_offset {byte_offset} "
                      f"out of range (packet len {len(packet)})")

        out += header
        out += packet
        offset += pkt_len
        current_frame += 1

    with open(outfile, "wb") as f:
        f.write(out)
    print(f"Wrote {len(out)} bytes to {outfile}")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: modify_packet.py <in.bin> <out.bin> <frame_idx> <byte_offset> [new_value]")
        sys.exit(1)
    infile = sys.argv[1]
    outfile = sys.argv[2]
    frame_idx = int(sys.argv[3])
    byte_offset = int(sys.argv[4])
    new_value = int(sys.argv[5], 16) if len(sys.argv) > 5 else None
    modify_packet(infile, outfile, frame_idx, byte_offset, new_value)
