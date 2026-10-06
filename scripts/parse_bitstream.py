import struct

with open("data/bitstreams/hybrid_try.bit", "rb") as f:
    data = f.read()

print(f"Total file size: {len(data)} bytes")
offset = 0
frame_idx = 0
while offset + 4 <= len(data):
    pkt_len = struct.unpack(">I", data[offset:offset+4])[0]
    print(f"Frame {frame_idx}: pkt_len={pkt_len}, pkt_offset={offset+4}")
    offset += 4 + pkt_len + 8
    frame_idx += 1
