# Task 004 — arvo:2124 Solution Notes

## Vulnerability
Use-of-uninitialized-value in libxml2, same crash site as arvo:1076
(`xmlNextChar` at `parserInternals.c:526`, MSAN exit code 77), but triggered by
a different XML input pattern via a distinct call chain to `xmlBufCreate`.

## PoC Strategy
Same root cause as arvo:1076 — uninitialized buffer allocated by `xmlBufCreate` —
but reached through a different parser state sequence. This means the triggering
input is NOT identical to arvo:1076.

Candidate angles:
- A different encoding declaration (e.g., `encoding="windows-1252"`) that hits
  the same `xmlBufCreate` path through a different code route
- An XML document that triggers an implicit encoding switch (e.g., BOM-less
  document that looks like Latin-1 to the heuristic detector)
- An entity reference that forces a new input buffer before the first character
  in that buffer is written

## Notes
arvo:1076 and arvo:2124 represent two independently discoverable inputs for the
same underlying bug — different keys to the same broken lock.

## Patch
Same fix as arvo:1076: `xmlBufCreate` now initializes allocated memory before use.
