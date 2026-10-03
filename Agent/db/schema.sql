-- PostgreSQL schema for users, sessions, and messages.
-- Run: psql -U postgres -d sessions -f Agent/db/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at ASC);

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
