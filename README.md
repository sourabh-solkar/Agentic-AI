# Agentic AI

LangGraph agent with FastAPI backend, Streamlit UI, and optional MCP server.

## Setup

```powershell
# From repo root
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
```

Or install from the lock-style requirements file:

```powershell
pip install -r requirements.txt
```

## Environment

Copy `.env.example` to `.env` and set your keys (see project docs). Required variables include `GEMINI_API_KEY`, `SECREAT_KEY`, and `ALGORITHM`.

## Run

**Agent API** (port 9005):

```powershell
cd Agent
python main.py
```

**Streamlit UI**:

```powershell
cd UI
streamlit run app.py
```

**MCP server**:

```powershell
cd MCP
python server.py
```

## Dependencies

Project dependencies are declared in `pyproject.toml`. After adding or changing a package:

```powershell
pip install -e .
```

To record exact versions for reproducible installs:

```powershell
pip freeze > requirements.lock.txt
```
