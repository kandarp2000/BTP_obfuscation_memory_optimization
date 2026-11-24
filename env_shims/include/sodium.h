/* Minimal libsodium header for the OBSCURE runtime (dev headers not installed). */
#ifndef SODIUM_SHIM_H
#define SODIUM_SHIM_H
int sodium_init(void);
int crypto_box_seal_open(unsigned char *m, const unsigned char *c, unsigned long long clen,
                         const unsigned char *pk, const unsigned char *sk);
#endif
