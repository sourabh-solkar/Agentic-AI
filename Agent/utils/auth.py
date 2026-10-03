import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv

load_dotenv()
SECREAT_KEY = os.getenv("SECREAT_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECREAT_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_access_token(username: str, user_id: str) -> str | None:
    try:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode = {
            "username": username,
            "user_id": user_id,
            "exp": expire,
        }
        return jwt.encode(to_encode, SECREAT_KEY, algorithm=ALGORITHM)
    except Exception:
        return None
