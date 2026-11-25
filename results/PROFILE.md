# Profiling findings (baseline, tracemalloc inside universalize())

| Program | SE | held at end (MB) | of which routing (add_permutation) | peak (MB) | peak above end (MB) | universalize time with profiling (s) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| AES | small | 42.0 | 91% | 42.0 | 0.00 | 6.0 |
| AES | medium | 17.1 | 91% | 17.2 | 0.01 | 2.6 |
| AES | large | 8.9 | 88% | 8.9 | 0.02 | 1.6 |
| AES | xlarge | 2.0 | 96% | 2.3 | 0.28 | 0.2 |
| Ascon | small | 367.1 | 93% | 367.8 | 0.00 | 59.6 |
| Ascon | medium | 172.1 | 86% | 172.2 | 0.12 | 47.8 |
| Ascon | large | 44.0 | 89% | 44.1 | 0.02 | 9.5 |
| Ascon | xlarge | 25.3 | 92% | 26.7 | 1.38 | 4.8 |
| TinyJambu | small | 33.8 | 90% | 34.4 | 0.22 | 4.3 |
| TinyJambu | medium | 15.5 | 86% | 15.5 | 0.02 | 2.2 |
| TinyJambu | large | 13.9 | 91% | 14.1 | 0.10 | 2.2 |
| TinyJambu | xlarge | 13.8 | 92% | 13.8 | 0.04 | 2.5 |
| tracingAES | small | 109.0 | 95% | 109.3 | 0.00 | 25.2 |
| tracingAES | medium | 34.7 | 93% | 34.8 | 0.00 | 8.4 |
| tracingAES | large | 34.2 | 92% | 34.3 | 0.05 | 16.1 |
| tracingAES | xlarge | 16.5 | 93% | 16.6 | 0.08 | 7.6 |
| sum_tree | small | 90.7 | 96% | 94.3 | 3.45 | 144.7 |
| sum_tree | medium | 17.1 | 93% | 18.1 | 0.99 | 12.3 |
| sum_tree | large | 39.3 | 93% | 41.1 | 1.77 | 46.5 |
| sum_tree | xlarge | 38.5 | 92% | 41.0 | 2.46 | 111.0 |
| findmax_tree | small | 79.4 | 96% | 83.0 | 3.47 | 113.7 |
| findmax_tree | medium | 16.8 | 93% | 17.8 | 1.00 | 12.6 |
| findmax_tree | large | 32.3 | 94% | 34.1 | 1.76 | 37.9 |
| findmax_tree | xlarge | 38.3 | 92% | 40.8 | 2.47 | 58.6 |
