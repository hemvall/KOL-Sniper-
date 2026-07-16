# Security

## Immediate secret rotation

`sniper_session.session` was committed to this repository. Deleting it from the working tree does **not** invalidate the Telegram authorization key stored in Git history.

- Revoke the affected Telegram session and create a new one.
- Rotate any wallet key, bot token or API secret that may have been exposed with the repository.
- Rewrite Git history before publication and coordinate the rewrite with every clone owner.

Never report a leaked secret in a public issue. Contact the repository owner privately.

## Runtime model

- Live mode requires explicit `DRY_RUN=false` and complete validated configuration.
- A dedicated, minimally funded hot wallet is mandatory.
- Third-party transactions are untrusted input and are validated before signing.
- The service is intended for one active process per wallet until distributed locking is implemented.
- The admin bot is read-only and authorizes the Telegram user IDs listed in `ADMIN_USER_IDS`.

## Upstream JavaScript advisory

The official Pump SDK currently pulls Solana packages that depend on `bigint-buffer`, for which npm reports `GHSA-3gc7-fjrx-p6mg` without a non-breaking upstream fix. In production, the SDK runs as a separate Docker service or OS user that receives only the RPC URL and public/scalar trade input; it never receives the wallet private key. The signing service independently validates the serialized output before signing. The local subprocess mode is a development convenience, not an OS security boundary. Do not collapse the production boundary, and update the SDK as soon as upstream resolves the advisory.
