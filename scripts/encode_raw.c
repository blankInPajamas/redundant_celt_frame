#include <opus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FRAME_SIZE 960      /* 20 ms at 48 kHz */
#define SAMPLE_RATE 48000
#define CHANNELS 1
#define MAX_PACKET 1500

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "Usage: %s <input.pcm> <output.bin> <mode> <bitrate> "
                        "[complexity=10] [fec=0] [loss_pct=0]\n", argv[0]);
        fprintf(stderr, "  mode: voip | audio | lowdelay\n");
        fprintf(stderr, "  fec: 0 or 1 (default 0 — previously was hardcoded to 1 "
                        "for every run; set explicitly per-experiment now)\n");
        return 1;
    }

    const char *infile  = argv[1];
    const char *outfile = argv[2];
    const char *mode    = argv[3];
    int bitrate         = atoi(argv[4]);
    int complexity      = (argc > 5) ? atoi(argv[5]) : 10;
    int fec             = (argc > 6) ? atoi(argv[6]) : 0;   /* default OFF now */
    int loss_pct        = (argc > 7) ? atoi(argv[7]) : 0;

    int application;
    if (strcmp(mode, "voip") == 0)          application = OPUS_APPLICATION_VOIP;
    else if (strcmp(mode, "audio") == 0)    application = OPUS_APPLICATION_AUDIO;
    else if (strcmp(mode, "lowdelay") == 0) application = OPUS_APPLICATION_RESTRICTED_LOWDELAY;
    else { fprintf(stderr, "Unknown mode: %s\n", mode); return 1; }

    int err;
    OpusEncoder *enc = opus_encoder_create(SAMPLE_RATE, CHANNELS,
                                           application, &err);
    if (err != OPUS_OK) {
        fprintf(stderr, "opus_encoder_create failed: %s\n", opus_strerror(err));
        return 1;
    }

    opus_encoder_ctl(enc, OPUS_SET_BITRATE(bitrate));
    opus_encoder_ctl(enc, OPUS_SET_COMPLEXITY(complexity));
    opus_encoder_ctl(enc, OPUS_SET_SIGNAL(OPUS_AUTO));
    opus_encoder_ctl(enc, OPUS_SET_INBAND_FEC(fec));
    opus_encoder_ctl(enc, OPUS_SET_PACKET_LOSS_PERC(loss_pct));

    fprintf(stderr, "CONFIG: mode=%s bitrate=%d complexity=%d fec=%d loss_pct=%d\n",
            mode, bitrate, complexity, fec, loss_pct);

    FILE *fin  = fopen(infile, "rb");
    FILE *fout = fopen(outfile, "wb");
    if (!fin || !fout) { fprintf(stderr, "File open failed\n"); return 1; }

    short pcm[FRAME_SIZE];
    unsigned char packet[MAX_PACKET];
    int frame_idx = 0;
    int total_packets = 0;

    while (fread(pcm, sizeof(short), FRAME_SIZE, fin) == FRAME_SIZE) {
        int len = opus_encode(enc, pcm, FRAME_SIZE, packet, MAX_PACKET);
        if (len < 0) {
            fprintf(stderr, "opus_encode failed at frame %d: %s\n",
                    frame_idx, opus_strerror(len));
            break;
        }

        /* Write simple [4-byte length][packet] format */
        int len_le = len;
        fwrite(&len_le, sizeof(int), 1, fout);
        fwrite(packet, 1, len, fout);

        fprintf(stderr, "FRAME %d: len=%d\n", frame_idx, len);
        frame_idx++;
        total_packets++;
    }

    fprintf(stderr, "Encoded %d packets\n", total_packets);

    fclose(fin);
    fclose(fout);
    opus_encoder_destroy(enc);
    return 0;
}
