# pip-audit exception register

| Advisory | Package | Review by | Reason and compensating control |
| --- | --- | --- | --- |
| `PYSEC-2026-2858` | Paramiko 4.0.0 | 2026-11-08 | The advisory has no fixed release and concerns RSA/SHA-1 (`ssh-rsa`). Both SSH and SFTP connection paths pass `disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]}`. Strict host-key checking remains the default. Remove this exception as soon as Paramiko publishes a release containing upstream commit `a448945` or later. |

Exceptions must name one advisory, document a code-level mitigation, and have
a review deadline. Broad package or scanner exclusions are not permitted.
