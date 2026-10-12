# Deploying the StartRight chat site (free tier)

The site is a FastAPI app (`src/startright/webapp.py`) that serves one page and a small
streaming API. On Render it runs **without any embedding model** (`RETRIEVAL_MODE=bm25_light`,
keyword search), so it fits a 512 MB free server. Locally you can use any search mode.

## 1. Run it on your computer first
```bash
docker compose up -d db
uvicorn startright.webapp:app --port 8002
```
Open http://127.0.0.1:8002. (Port 8000 is used by the Week 3 API container.)

## 2. Put the documents in a hosted database (Neon, free)
1. In the Neon console open your project and copy the **connection string**
   (it ends in `?sslmode=require`).
2. Copy the data from your local database. No re-embedding is needed:
```bash
export TARGET_DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
python -m startright.cli copydb
unset TARGET_DATABASE_URL
```
3. Check it: `Copied 2785 chunks ...` (the number may differ slightly after re-ingesting).

## 3. Create the Render service
Use **New > Web Service**, connect the GitHub repo, then set:

| Setting | Value |
|---|---|
| Runtime | Docker |
| Dockerfile path | `./Dockerfile.web` |
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
| `ACCESS_CODE` | optional: a code visitors must type |

`render.yaml` in the repo describes the same service if you prefer a Blueprint.

## 4. After it is live
- The free plan sleeps when idle; the first visit can take about a minute (the page says so).
- Open **Behind the scenes > Usage** to see requests, tokens and timings since the last start.
- If Groq's free quota runs out, the page shows a friendly message instead of crashing.
- To pause the public site, set `DAILY_TOKEN_BUDGET` to `0` or delete the service.

## 5. Safety notes
- Never put keys in Git. Rotate any key that was ever pasted into a file or chat.
- Questions are not stored; only sizes and timings are kept in memory.
- Personal-data masking is planned for Week 10. Until then, tell users not to type ID numbers or phone numbers.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Build fails on Render | read the build log; confirm Dockerfile path is `./Dockerfile.web` |
| Page loads, answers say "database is not reachable" | wrong `DATABASE_URL`, or the Neon project is paused |
| `/api/info` shows `model: not set` | `GROQ_MODEL` missing in Render |
| Every answer is "too many questions" | `RATE_LIMIT_PER_HOUR` is low or many users share one IP |
| "Today's free demo budget is used up" | raise `DAILY_TOKEN_BUDGET` or wait for the UTC day to change |
