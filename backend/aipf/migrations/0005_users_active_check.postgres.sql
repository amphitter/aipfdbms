ALTER TABLE users ADD CONSTRAINT users_active_check CHECK (active IN (0, 1));
