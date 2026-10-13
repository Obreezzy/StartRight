# Deploying the StartRight chat site (free tier)

The site is a FastAPI app (`src/startright/webapp.py`) that serves one page and a small
streaming API. On Render it runs **without any embedding model** (`RETRIEVAL_MODE=bm25_light`,
keyword search), so it fits a 512 MB free server. Locally you can use any search mode.

Commands below are for **PowerShell on Windows**, run from the project folder with the
virtual environment active.

## 1. Run it on your computer first
```powershell
docker compose up -d db
uvicorn startright.webapp:app --port 8002
```
Open http://127.0.0.1:8002 (use `127.0.0.1`, not `localhost`: on Windows `localhost` can try
IPv6 first and stall). Port 8000 is used by the Week 3 API container.

## 2. Put the documents in a hosted database (Neon, free)
1. Sign up at neon.tech and create a project. Pick the AWS region **US East (N. Virginia)**
   (`us-east-1`), and use the same region for Render in step 3 so the two are close.
2. In the project, click **Connect** and copy the **connection string**. Use the normal
   (direct) one for the copy and for the app. It looks like
   `postgresql://user:password@ep-xxxx.us-east-1.aws.neon.tech/neondb?sslmode=require`.
   If Neon offers a "pooled" string, that also works: the app disables prepared statements for it.
3. Copy the data from your local database. No re-embedding is needed. Local Docker database
   must be running (`docker compose up -d db`):
```powershell
$env:TARGET_DATABASE_URL = "postgresql://...neon.tech/neondb?sslmode=require"
python -m startright.cli copydb
Remove-Item Env:TARGET_DATABASE_URL
```
4. Check it: `Copied 2785 chunks ...` (the number may differ slightly after re-ingesting).
   The command creates the tables on Neon for you.

The connection string contains a password. Do not paste it into a file in the repo or into chat.

## 3. Create the Render service
1. Sign up at render.com with GitHub. Push your branch and merge it first, so `main` has
   `Dockerfile.web`.
2. **New > Web Service**, choose the repo, then set:

| Setting | Value |
|---|---|
| Runtime | Docker |
| Dockerfile path | `./Dockerfile.web` |
| Region | Virginia (US East), same as Neon |
| Instance type | Free |
| Health check path | `/api/health` |

Environment variables (Render dashboard, never in Git):

| Key | Value |
|---|---|
| `GROQ_API_KEY` | your Groq key |
| `GROQ_MODEL` | `openai/gpt-oss-20b` |
| `DATABASE_URL` | the Neon connection string |
| `RETRIEVAL_MODE` | `bm25_light` |
| `LEXICAL_MIN_SCORE` | `0.3` |
| `RATE_LIMIT_PER_HOUR` | `15` (questions per visitor per hour) |
| `DAILY_TOKEN_BUDGET` | `60000` (all visitors together, per UTC day) |
| `ACCESS_CODE` | recommended: a code visitors must type |

`render.yaml` in the repo describes the same service if you prefer a Blueprint.
Traces are written to `/tmp/traces.jsonl` inside the container (set in `Dockerfile.web`);
they are lost on every restart, which is fine for a demo. See `docs/observability.md` for Langfuse.

## 4. Staging parity: prove local and hosted behave the same
Week 3 asks that the app "runs identically locally and in staging". Show it with evidence.
With the local app running and the Render site awake, run:

```powershell
python scripts/parity_check.py http://127.0.0.1:8002 https://YOUR-APP.onrender.com --out docs/parity-report.md
```
If you set `ACCESS_CODE`, add `--code YOUR_CODE`.

The script asks 3 fixed questions of both sites and checks: both healthy, same model, the
same kind of result, and at least one shared cited source. It does **not** compare wording,
because the model varies between runs. It writes `docs/parity-report.md`; commit that file
as your evidence. Exit code 0 means every check passed.

Expected difference: local may use `hybrid_rerank` while Render uses `bm25_light`. To compare
like with like, start the local app with `$env:RETRIEVAL_MODE = "bm25_light"` on its own line
first. The check uses 3 of each site's 15 hourly questions, so run it sparingly.

## 5. After it is live
- The free plan sleeps when idle; the first visit can take about a minute (the page says so).
- Open **Behind the scenes > Usage** and **Cost & speed** to see requests, tokens and timings.
- If Groq's free quota runs out, the page shows a friendly message instead of crashing.
- To pause the public site, set `DAILY_TOKEN_BUDGET` to `0` or delete the service.

## 6. Safety notes
- Never put keys in Git. Rotate any key that was ever pasted into a file or chat.
- Questions are not stored; only sizes and timings are kept (the trace file holds no question text).
- Personal-data masking is planned for Week 10. Until then, tell users not to type ID numbers or phone numbers.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Build fails on Render | read the build log; confirm Dockerfile path is `./Dockerfile.web` |
| Page loads, answers say "database is not reachable" | wrong `DATABASE_URL`, or the Neon project is paused |
| `/api/info` shows `model: not set` | `GROQ_MODEL` missing in Render |
| Every answer is "too many questions" | `RATE_LIMIT_PER_HOUR` is low or many users share one IP |
| "Today's free demo budget is used up" | raise `DAILY_TOKEN_BUDGET` or wait for the UTC day to change |
| Parity script exits 2 | one site is unreachable; wake Render by opening it in a browser, then rerun |

## Optional: Cohere Rerank on the hosted site
`RETRIEVAL_MODE=bm25_cohere` keeps the model-free keyword search, then re-ranks the top candidates with
Cohere Rerank. It needs no extra memory. Add `COHERE_API_KEY` (Render dashboard only) and set
`RETRIEVAL_MODE` to `bm25_cohere`. If Cohere is unreachable or over quota the site falls back to the
plain keyword order. The question and public passages are sent to Cohere; list this in the Week 10 data-flow
diagram. Free trial keys have a low per-minute limit; set `COHERE_MIN_INTERVAL=7` when benchmarking.
