"""Validate required env vars before starting the API server."""

import os
import sys

REQUIRED_VARS = ("GEMINI_API_KEY", "SECREAT_KEY")


def main() -> None:
    missing = [name for name in REQUIRED_VARS if not os.getenv(name, "").strip()]
    if missing:
        print("Missing required environment variables:", ", ".join(missing), file=sys.stderr)
        print(
            "Provide them with: docker run --env-file .env ... "
            "or -e GEMINI_API_KEY=... -e SECREAT_KEY=...",
            file=sys.stderr,
        )
        sys.exit(1)

    # Render/Cloud Run inject PORT; local Docker uses FASTAPI_PORT.
    port = os.getenv("PORT") or os.getenv("FASTAPI_PORT", "9005")
    os.execvp(
        "uvicorn",
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", port],
    )


if __name__ == "__main__":
    main()
