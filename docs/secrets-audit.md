# Secrets-management audit

Scope: every credential StartRight uses. Method: list each secret, say where it is stored and who can read
it, check the repository for leaks with `scripts/secret_scan.py`, and record how each is rotated.

## 1. Inventory

| Secret | Used for | Stored (local) | Stored (hosted) | Who can read it | Rotate by |
|---|---|---|---|---|---|
| `GROQ_API_KEY` | Language model calls | `.env` (ignored by Git) | Render env var | Me; Render account | console.groq.com > API Keys > delete, create new |
| `COHERE_API_KEY` | Optional reranking | `.env` | Render env var (only if used) | Me; Render account | dashboard.cohere.com > API Keys |
| `DATABASE_URL` / `TARGET_DATABASE_URL` | Neon database (contains a password) | `.env` / one-off shell variable | Render env var | Me; Render account | Neon console > reset role password |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Optional trace export | `.env` | Render env var | Me; Render account | Langfuse project settings > API keys |
| `ACCESS_CODE` | Gate for the public demo | `.env` | Render env var | Me; Render account | Change the env var and redeploy |
| GitHub access | Source code | Git credential manager | n/a | Me | Revoke the token in GitHub settings |

## 2. Controls in place

| Control | How it works | Evidence |
|---|---|---|
| Keys live in environment variables, never in code | The app reads `os.getenv(...)` | `grep -r "gsk_" src` finds nothing; scan report |
| `.env` is ignored by Git | `.gitignore` lists `.env` | `scripts/secret_scan.py` checks it |
| Placeholders only in committed files | `.env.example`, `render.yaml` (`sync: false`), docs use fake values | Scan report |
| Secrets are not logged or traced | Traces hold timings and counts, not request headers or keys | `docs/observability.md`; `tests/test_observability.py` |
| Hosted secrets are entered in the Render dashboard | `render.yaml` marks them `sync: false` so they are never in the repo | `render.yaml` |
| Secret scan before merging | `python scripts/secret_scan.py --history` | `docs/secret-scan-report.md` |

## 3. Incident log

| Date | What happened | Action |
|---|---|---|
| 2026-10-13 | A Cohere API key was visible in a terminal screenshot shared in a chat | Key deleted at Cohere and replaced; new key stored in `.env` only; checked `.env` is ignored |
| (earlier) | Rule adopted: any key pasted into a file or chat is treated as leaked | Rotate immediately |

Lesson recorded: set secrets by reading them from `.env` or typing them where the terminal does not echo,
and crop screenshots before sharing.

## 4. Gaps and what a larger team would add

| Gap | Why it is acceptable now | Next step |
|---|---|---|
| No secrets manager (Vault) | One developer, one service, free tiers; a Vault server would need hosting | Demonstrate HashiCorp Vault in dev mode locally for the audit; use a managed secrets store in production |
| No automatic rotation | Few keys, quick manual rotation | Schedule rotation (for example every 90 days); Vault can issue short-lived database credentials |
| No access log for who read a secret | Single user | Use a store with audit logging |
| Secret scan is manual | Short project | Run it in CI and add GitHub secret scanning / push protection |
| Render dashboard holds all secrets in one place | Free plan has no separate roles | Restrict the Render account with two-factor authentication |

## 5. How to run the checks
```powershell
python scripts/secret_scan.py --history --out docs/secret-scan-report.md
```
Exit code 0 means nothing found. Commit the report as evidence. If it flags something: remove it, rotate the key
at the provider, and add a row to the incident log. A secret that was ever committed stays in Git history, so
rotating the key is the only real fix.
