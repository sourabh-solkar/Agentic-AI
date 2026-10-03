# Free deploy: Neon + Render + Streamlit Cloud

Target stack for a public LinkedIn demo:

| Piece | Host |
|-------|------|
| Postgres | Neon (already linked) |
| Agent API | [Render](https://render.com) free web service |
| UI | [Streamlit Community Cloud](https://share.streamlit.io) |

## 0. Push this branch to GitHub

Render and Streamlit deploy from GitHub. From the repo root:

```powershell
git add Agent/main.py Agent/docker_entrypoint.py UI/app.py render.yaml docs/DEPLOY_FREE.md env-dev.example README.md
git commit -m "Prepare Render + Streamlit Cloud deployment"
git push -u origin HEAD
```

Do **not** commit `.env`.

## 1. Deploy Agent API on Render

1. Sign in at [dashboard.render.com](https://dashboard.render.com) with GitHub.
2. **New** → **Blueprint** → select `sourabh-solkar/Agentic-AI` (GitHub) → branch `context-try`.
   - Or **New** → **Web Service** → same repo:
     - **Root Directory:** `Agent`
     - **Runtime:** Python 3
     - **Build:** `pip install -r requirements.txt`
     - **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
     - **Health check path:** `/health`
3. Set **Environment** (copy from local `.env`, never paste into git):

   | Key | Notes |
   |-----|--------|
   | `DATABASE_URL` | Neon pooled URL from `.env` |
   | `SECREAT_KEY` | JWT secret |
   | `ALGORITHM` | `HS256` |
   | `GEMINI_API_KEY` | required |
   | `GROQ_API_KEY` | optional fallback |
   | `XAI_API_KEY` | optional |
   | `CORS_ALLOW_ALL` | `true` for the demo |
   | `TOKENS_PER_CREDIT` / `CREDIT_HOLD_AMOUNT` / `MIN_CREDITS_PER_TURN` | billing defaults |
   | `LANGSMITH_TRACING` | `false` unless you want traces |

4. Deploy. Open `https://<your-service>.onrender.com/health` → `{"status":"ok"}`.

Free tier **spins down** after idle; the first request after sleep can take ~30–60s.

## 2. Deploy UI on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
2. Repo: `sourabh-solkar/Agentic-AI`, branch `context-try`.
3. **Main file path:** `UI/app.py`
4. **Advanced settings → Secrets** (TOML):

```toml
FASTAPI_BASE_URL = "https://<your-service>.onrender.com"
```

Streamlit maps secrets into `os.environ` for many keys; if your Cloud version only injects `st.secrets`, add this near the top of `UI/app.py` only if needed:

```python
# Optional bridge if Cloud secrets are not exported as env:
try:
    if not os.getenv("FASTAPI_BASE_URL") and "FASTAPI_BASE_URL" in st.secrets:
        os.environ["FASTAPI_BASE_URL"] = st.secrets["FASTAPI_BASE_URL"]
except Exception:
    pass
```

(This repo already prefers `FASTAPI_BASE_URL` from the environment.)

5. Deploy. Open the Streamlit URL → register/login → chat.

## 3. LinkedIn checklist

1. Hit the API `/health` and open the Streamlit app once (wake free tiers).
2. Share the **Streamlit** URL (not the API).
3. Mention cold start: “first load may take a minute on the free tier.”

## Local vs prod

| | Local | Prod |
|--|-------|------|
| DB | Neon `DATABASE_URL` in `.env` | same URL in Render env |
| API | `python main.py` → `:9005` | Render `$PORT` |
| UI | `streamlit run app.py` | Streamlit Cloud + `FASTAPI_BASE_URL` |
