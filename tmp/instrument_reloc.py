#!/usr/bin/env python3
"""Instrument the OPUS_MOVE relocation site and re-instrument FINAL log.
Run from project root. Backs up first."""
import pathlib, shutil, sys

FILE = pathlib.Path("opus/src/opus_encoder.c")
BACKUP = pathlib.Path("/tmp/opus_encoder_before_reloc_instrument.c")

if not FILE.exists():
    print(f"ERROR: {FILE} not found. Run from project root.")
    sys.exit(1)

# Backup
if not BACKUP.exists():
    shutil.copy2(FILE, BACKUP)
    print(f"Backup written to {BACKUP}")

src = FILE.read_text()

# --- Targeted replacement 1: the relocation block ---
OLD_BLOCK = '''           /* Put CELT->SILK redundancy data in the right place. */
           if (redundancy && celt_to_silk && st->mode==MODE_HYBRID && nb_compr_bytes != ret)
           {
              OPUS_MOVE(data+ret, data+nb_compr_bytes, redundancy_bytes);
              nb_compr_bytes = ret+redundancy_bytes;
           }'''

NEW_BLOCK = '''           /* --- RELOCATION DIAGNOSTIC --- */
           fprintf(stderr, "  -> PRE_MOVE: ret=%d nb_compr_bytes=%d max_data_bytes=%d redundancy=%d celt_to_silk=%d mode=%d\\n",
                   ret, nb_compr_bytes, max_data_bytes, redundancy, celt_to_silk, st->mode);
           /* Put CELT->SILK redundancy data in the right place. */
           if (redundancy && celt_to_silk && st->mode==MODE_HYBRID && nb_compr_bytes != ret)
           {
              fprintf(stderr, "  -> MOVE_ENTERED: from=data+%d to=data+%d size=%d; first8_src: %02x %02x %02x %02x %02x %02x %02x %02x\\n",
                      nb_compr_bytes, ret, redundancy_bytes,
                      data[nb_compr_bytes], data[nb_compr_bytes+1], data[nb_compr_bytes+2], data[nb_compr_bytes+3],
                      data[nb_compr_bytes+4], data[nb_compr_bytes+5], data[nb_compr_bytes+6], data[nb_compr_bytes+7]);
              OPUS_MOVE(data+ret, data+nb_compr_bytes, redundancy_bytes);
              nb_compr_bytes = ret+redundancy_bytes;
              fprintf(stderr, "  -> POST_MOVE: ret=%d new_nb_compr_bytes=%d; first8_dst: %02x %02x %02x %02x %02x %02x %02x %02x\\n",
                      ret, nb_compr_bytes,
                      data[ret], data[ret+1], data[ret+2], data[ret+3],
                      data[ret+4], data[ret+5], data[ret+6], data[ret+7]);
           }
           else
           {
              fprintf(stderr, "  -> MOVE_SKIPPED: redundancy=%d celt_to_silk=%d is_hybrid=%d nb_compr_bytes=%d ret=%d equal=%d\\n",
                      redundancy, celt_to_silk, (st->mode==MODE_HYBRID),
                      nb_compr_bytes, ret, (nb_compr_bytes == ret));
           }
           /* --- END RELOCATION DIAGNOSTIC --- */'''

if OLD_BLOCK not in src:
    print("ERROR: original relocation block not found verbatim. Aborting.")
    print("This means the source has drifted. Check with:")
    print("  sed -n '2320,2330p' opus/src/opus_encoder.c")
    sys.exit(1)

src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)
print("Relocation instrumentation applied.")

# --- Targeted replacement 2: FINAL packet log adds nb_compr_bytes ---
OLD_FINAL = '''    fprintf(stderr, "  -> FINAL packet: frame_id=%d ret=%d, mode=%d, "
        "redundancy_region=[%d,%d)\\n",
        this_frame_id, ret, st->mode,
        dbg_redundancy_region_start,
        dbg_redundancy_region_start < 0 ? -1 : dbg_redundancy_region_start + dbg_redundancy_region_size);'''

NEW_FINAL = '''    fprintf(stderr, "  -> FINAL packet: frame_id=%d ret=%d nb_compr_bytes=%d mode=%d, "
        "redundancy_region=[%d,%d)\\n",
        this_frame_id, ret, nb_compr_bytes, st->mode,
        dbg_redundancy_region_start,
        dbg_redundancy_region_start < 0 ? -1 : dbg_redundancy_region_start + dbg_redundancy_region_size);'''

if OLD_FINAL in src:
    src = src.replace(OLD_FINAL, NEW_FINAL, 1)
    print("FINAL packet log updated to include nb_compr_bytes.")
else:
    print("WARNING: FINAL packet log block not found. Skipping that edit.")
    print("Find it with: grep -n 'FINAL packet' opus/src/opus_encoder.c")

FILE.write_text(src)
print()
print("Instrumentation complete. Verifying:")

src_verify = FILE.read_text()
checks = [
    ("PRE_MOVE log", "PRE_MOVE: ret="),
    ("MOVE_ENTERED log", "MOVE_ENTERED:"),
    ("POST_MOVE log", "POST_MOVE: ret="),
    ("MOVE_SKIPPED log", "MOVE_SKIPPED:"),
    ("FINAL nb_compr_bytes", "nb_compr_bytes=%d mode=%d"),
]
for name, needle in checks:
    print(f"  {'[OK]' if needle in src_verify else '[MISSING]'} {name}")

