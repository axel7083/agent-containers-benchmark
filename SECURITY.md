# Security model

Agents under test run arbitrary commands in a **privileged** container (nested Podman needs it).
Treat every job that runs an agent as fully compromised: a privileged container can reach the
runner host. The design therefore assumes an agent can read anything on its runner, and makes
sure there is nothing valuable there.

## Secrets

| Secret | Where it lives | Which jobs can read it | Blast radius if leaked |
|---|---|---|---|
| `OPENROUTER_MANAGEMENT_KEY` | environment `openrouter-admin` (branch policy: `main`); must not also exist as a repository secret | `provision`, `revoke` only | account-wide: can mint keys |
| `ACB_UNSEAL_KEY` (RSA private key) | environment `bench-runner` (branch policy: `main`) | `run` | decrypts sealed child keys of the current run only |
| per-shard OpenRouter child key | memory of the metering proxy on the `run` runner | `run` | capped (a few USD), expires within 5 h, revoked at run end |
| per-run client token | agent containers | `run` | none: only valid against the proxy, which dies with the job |

Flow:

1. `provision` (no agent, no third-party code besides `actions/checkout`; a sparse checkout of
   `scripts/openrouter_keys.py` only) checks remaining credits, creates **one child key per
   shard** with a spending `limit` and an `expires_at`, masks it, and **seals** it with the
   repository RSA public key (`.github/acb-seal.pub.pem`, OAEP-SHA256). Only the sealed blob
   leaves the job, as a job output.
2. `run` decrypts its blob inside a pipe straight into the metering proxy's stdin: the child key
   never touches disk or an environment variable, and the unseal key is scrubbed from the
   proxy's environment. The proxy binds the runner's primary address (rootless containers reach
   it through pasta's host-gateway mapping; loopback-only services stay unreachable), forwards
   only inference endpoints, forces the configured model, and swaps the client token for the
   real key.
3. Agents get the proxy URL and a random client token as their "API key".
4. `revoke` (`if: always()`) records each child key's billed usage, deletes it, and sweeps any
   `acb-*` key older than 6 hours left by an aborted run.

Artifacts are scanned for anything shaped like an OpenRouter key before upload; the job fails
instead of uploading if one is found.

## GitHub hardening

- Workflow-level `permissions: {}`; each job requests the minimum. The agent job has a read-only
  token (`contents: read`). Only `aggregate` has `contents: write`, and only
  its final step (which runs no artifact-derived code) uses the token.
- `actions/checkout` with `persist-credentials: false` everywhere.
- Every action is pinned to a full commit SHA; only GitHub-owned actions are used.
- Python dependencies are installed from hash-locked requirement files (`--require-hashes`).
- No `pull_request_target`; fork PRs only run `ci.yml`, which has no secrets.
- No Actions cache anywhere (a compromised runner could poison it).
- Environment secrets are restricted to the `main` branch.
- Artifacts from agent jobs are treated as untrusted data by the aggregator (parsed, never
  executed); the site renders them as text only.

## Reporting

Please report security issues privately via GitHub security advisories on this repository.
