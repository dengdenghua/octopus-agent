# pip-audit exception register

## Active exceptions

None.

Exceptions must name one advisory, document a code-level mitigation, and have
a review deadline. Broad package or scanner exclusions are not permitted.

## Retired exceptions

| Advisory | Package | Retired on | Resolution |
| --- | --- | --- | --- |
| `PYSEC-2026-2858` / `CVE-2026-44405` | Paramiko 4.0.0 | 2026-08-21 | Upgraded the `mantle-ssh` and `all` extras to Paramiko 5.0.0 or newer. The 5.0.0 release includes upstream commit `a448945` and removes RSA/SHA-1 signing and verification support. No scanner suppression remains. |
