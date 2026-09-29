ALTER TABLE users ADD COLUMN last_login_at TEXT;
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
