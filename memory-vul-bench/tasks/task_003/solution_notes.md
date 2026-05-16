# Task 003 — arvo:1076 Solution Notes

## Vulnerability
Use-of-uninitialized-value in libxml2's core XML parsing path, detected by
MemorySanitizer (MSAN, exit code 77).
`xmlNextChar` at `parserInternals.c:526` reads from a buffer allocated by
`xmlBufCreate` (via `malloc`) without prior initialization. The path is triggered
by an encoding declaration that exercises `xmlSwitchToEncodingInt` →
`xmlSwitchInputEncodingInt` → `xmlBufCreate` → uninitialized read in `xmlNextChar`.

## PoC Strategy
The input must carry an XML encoding declaration that:
1. Is accepted by the initial parser pass (syntactically valid declaration)
2. Triggers `xmlSwitchInputEncodingInt` (i.e., a non-UTF-8, non-ASCII encoding)
3. Causes `xmlBufCreate` to allocate a new buffer without zeroing it
4. Then reads from that buffer in `xmlNextChar` before any write

Candidate inputs:
- `<?xml version="1.0" encoding="ISO-8859-1"?>` followed by valid XML
- `<?xml version="1.0" encoding="UTF-16"?>` with a bare content byte
- Any encoding that forces a buffer switch mid-parse on the first character read
  after `xmlSwitchInputEncodingInt`

## Patch
Developer ensured the buffer is zeroed (`calloc` or `memset`) immediately after
allocation in `xmlBufCreate`.
