# Plate Reader Analyzer

Assumptions in this first implementation:

- Standard 96-well names are `A1-H12`.
- Time columns use the paired `T` suffix, for example `A1T` beside `A1`.
- Metadata rows are skipped until a header row with at least one time/signal well pair is found.
- Blank subtraction uses wells whose plate-map `role` is `blank`.
- Control normalization uses wells whose `role` is `vehicle` or `control`.
- Basic statistics intentionally use only Welch t-test for two groups or one-way ANOVA for three or more groups.

The modules are intentionally split into parser, plate map, normalization, metrics, stats, exports, and pipeline code so new reader formats and tests can be added without rewriting the web UI.
