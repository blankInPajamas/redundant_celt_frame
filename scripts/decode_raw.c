#include <opus.h>
#include <stdio.h>
#include <stdlib.h>

#define FRAME_SIZE 960
#define SAMPLE_RATE 48000
#define CHANNELS 1
#define MAX_PACKET 1500

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <input.bin> <output.pcm>\n", argv[0]);
        return 1;
    }

    FILE *fin  = fopen(argv[1], "rb");
    FILE *fout = fopen(argv[2], "wb");
    if (!fin || !fout) { fprintf(stderr, "File open failed\n"); return 1; }

    int err;
    OpusDecoder *dec = opus_decoder_create(SAMPLE_RATE, CHANNELS, &err);
    if (err != OPUS_OK) {
        fprintf(stderr, "opus_decoder_create failed: %s\n", opus_strerror(err));
        return 1;
    }

    unsigned char packet[MAX_PACKET];
    short pcm[FRAME_SIZE * 6];  /* max frame size */
    int frame_idx = 0;

    while (1) {
        int len;
        if (fread(&len, sizeof(int), 1, fin) != 1) break;
        if (len <= 0 || len > MAX_PACKET) {
            fprintf(stderr, "Invalid packet length %d at frame %d\n", len, frame_idx);
            break;
        }
        if (fread(packet, 1, len, fin) != (size_t)len) break;

        int samples = opus_decode(dec, packet, len, pcm, FRAME_SIZE * 6, 0);
        if (samples < 0) {
            fprintf(stderr, "opus_decode failed at frame %d: %s\n",
                    frame_idx, opus_strerror(samples));
            break;
        }

        fwrite(pcm, sizeof(short), samples, fout);
        frame_idx++;
    }

    fprintf(stderr, "Decoded %d frames\n", frame_idx);

    fclose(fin);
    fclose(fout);
    opus_decoder_destroy(dec);
    return 0;
}
