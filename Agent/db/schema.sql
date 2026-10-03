-- PostgreSQL schema for users, sessions, and messages.
-- Run: psql -U postgres -d sessions -f Agent/db/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    credits INTEGER NOT NULL DEFAULT 30 CHECK (credits >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New chat',
    current_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    summary TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'context')),
    content TEXT NOT NULL,
    trace_id TEXT,
    trace_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Upgrade older databases where sessions existed without user_id / title / timestamps.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT DEFAULT 'New chat';
UPDATE sessions SET title = 'New chat' WHERE title IS NULL;
ALTER TABLE sessions ALTER COLUMN title SET DEFAULT 'New chat';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
UPDATE sessions SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE sessions ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
UPDATE sessions SET updated_at = NOW() WHERE updated_at IS NULL;
ALTER TABLE sessions ALTER COLUMN updated_at SET DEFAULT NOW();

-- Upgrade older databases with optional LangSmith trace fields on messages.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS trace_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS trace_url TEXT;

-- Credits for free-tier questions (subscription gate).
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 30;
UPDATE users SET credits = 30 WHERE credits IS NULL;
ALTER TABLE users ALTER COLUMN credits SET DEFAULT 30;
ALTER TABLE users ALTER COLUMN credits SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at ASC);

-- Token-usage ledger + per-turn credit holds (hold → meter → settle).
-- session_id is stored without an FK: live DBs may use uuid or text for sessions.session_id.
CREATE TABLE IF NOT EXISTS credit_holds (
    run_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT,
    amount INTEGER NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'held'
        CHECK (status IN ('held', 'settled', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT,
    run_id UUID,
    provider TEXT,
    model TEXT,
    purpose TEXT NOT NULL DEFAULT 'chat',
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    credits_charged INTEGER NOT NULL DEFAULT 0 CHECK (credits_charged >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_holds_user_status
    ON credit_holds(user_id, status);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_created
    ON usage_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_run
    ON usage_events(run_id);

CREATE TABLE IF NOT EXISTS villas (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    type TEXT NOT NULL,
    rooms_available INTEGER NOT NULL CHECK (rooms_available >= 0),
    price_per_night NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    villa_id INTEGER NOT NULL REFERENCES villas(id),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT bookings_dates_check CHECK (check_out_date > check_in_date)
);

CREATE INDEX IF NOT EXISTS idx_bookings_villa ON bookings(villa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id, created_at DESC);

INSERT INTO villas (id, name, location, type, rooms_available, price_per_night)
VALUES
    (1, 'Sunset Beach Villa', 'Goa', 'both', 3, 200),
    (2, 'Hilltop Retreat Villa', 'Goa', 'veg', 5, 150),
    (3, 'Palm Grove Villa', 'Mumbai', 'veg', 0, 180),
    (4, 'Sea Breeze Villa', 'Mumbai', 'both', 2, 220),
    (5, 'Royal Heritage Villa', 'Delhi', 'non-veg', 4, 120)
ON CONFLICT (id) DO NOTHING;
