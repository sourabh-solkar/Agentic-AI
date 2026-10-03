# Technology Stack

This project is built with Python and is organized into three main parts:
- `Agent/` for the AI chat backend
- `API/` for sample/domain API endpoints
- `UI/` for the frontend web interface

## Core Language
- **Python**: primary language across backend, API, MCP server, and UI.

## Backend (AI Agent Service)
- **FastAPI**: HTTP API framework for endpoints like `/login` and `/chat`.
- **Uvicorn**: ASGI server used to run FastAPI apps.
- **Pydantic**: request/response data modeling (`BaseModel`).
- **FastAPI CORS Middleware**: cross-origin request support.
- **Server-Sent Events (SSE)**: streaming chat/approval responses from backend to UI (live graph `status` steps + final `message`; see [`docs/SSE_STREAMING.md`](docs/SSE_STREAMING.md)).
- **pyrate-limiter + fastapi-limiter**: request rate limiting.

## LLM and Agent Framework
- **LangChain**: agent creation and middleware integration.
- **Google Gemini (via `langchain_google_genai`)**: LLM provider (`gemini-2.5-flash` model in current code).
- **LangChain PII Middleware**: redaction/masking for sensitive user input.

## Authentication and Security
- **OAuth2PasswordBearer (FastAPI Security)**: bearer-token handling.
- **JWT (`PyJWT`)**: token generation and verification.
- **python-dotenv**: environment variable loading from `.env`.

## Frontend
- **Streamlit**: chat-style frontend UI for login and conversation.
- **requests**: HTTP calls for login and API operations.
- **urllib (stdlib)**: SSE stream consumption and URL handling.

## MCP Integration
- **FastMCP**: MCP server implementation in `MCP/server.py`.
- **SSE transport**: MCP server runs over SSE (`fastmcp.run(transport="sse", ...)`).

## Configuration and Runtime
- **Environment Variables (`.env`)**:
  - `GEMINI_API_KEY`
  - `FASTAPI_HOST`
  - `FASTAPI_PORT`
  - `API_URL` (used by MCP server)
- **Localhost service ports (current code defaults)**:
  - `9005` for Agent FastAPI app
  - `9000` for MCP server
  - `8000` for legacy/sample API routes referenced by MCP tools

## Repository Modules (High Level)
- `Agent/main.py`: main AI backend with auth, rate limiting, and SSE chat.
- `Agent/utils/auth.py`: JWT utility logic.
- `API/main.py` and `API/login.py`: domain/sample hotel API and auth flow.
- `UI/app.py`: Streamlit login + chat client.
- `MCP/server.py`: tools exposed as MCP endpoints.

