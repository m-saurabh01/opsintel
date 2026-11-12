MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE repositories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('local', 'gitea')),
    location TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_indexed_at TEXT,
    last_index_stats TEXT
);

CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    branch TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    language TEXT,
    size INTEGER NOT NULL,
    mtime_ns INTEGER,
    content_hash TEXT,
    commit_sha TEXT,
    encoding TEXT,
    line_count INTEGER,
    parser_name TEXT,
    parser_version TEXT,
    status TEXT NOT NULL CHECK (status IN ('indexed', 'skipped', 'unsupported', 'failed')),
    status_reason TEXT,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (repo_id, branch, path)
);
CREATE INDEX ix_files_repo_status ON files(repo_id, status);
CREATE INDEX ix_files_hash ON files(content_hash);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    coord_kind TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    page INTEGER,
    sheet TEXT,
    cell_ref TEXT,
    row_num INTEGER,
    section_path TEXT,
    key_path TEXT,
    extra_json TEXT,
    UNIQUE (file_id, ordinal)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2 tokenchars '_'"
);
CREATE VIRTUAL TABLE chunks_tri USING fts5(
    text, content='chunks', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
    INSERT INTO chunks_tri(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_tri(chunks_tri, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER chunks_au AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_tri(chunks_tri, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
    INSERT INTO chunks_tri(rowid, text) VALUES (new.id, new.text);
END;
""",
    ),
    (
        2,
        """
ALTER TABLE repositories ADD COLUMN gitea_id INTEGER;
ALTER TABLE repositories ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX ux_repositories_gitea_id ON repositories(gitea_id) WHERE gitea_id IS NOT NULL;

ALTER TABLE files ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;

CREATE TABLE repo_branches (
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    branch TEXT NOT NULL,
    head_sha TEXT,
    indexed_sha TEXT,
    indexed_at TEXT,
    last_sync_at TEXT,
    last_error TEXT,
    last_stats TEXT,
    PRIMARY KEY (repo_id, branch)
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    queue TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'dead', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 100,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    run_after REAL NOT NULL,
    leased_until REAL,
    worker_id TEXT,
    last_error TEXT,
    result TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE UNIQUE INDEX ux_jobs_queued_dedupe ON jobs(dedupe_key) WHERE status = 'queued';
CREATE INDEX ix_jobs_lease ON jobs(status, queue, priority, run_after);

CREATE TABLE webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    repo_full_name TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    job_id INTEGER
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
""",
    ),
    (
        3,
        """
CREATE TABLE parse_cache (
    content_hash TEXT NOT NULL,
    parser_sig TEXT NOT NULL,
    payload BLOB NOT NULL,
    size INTEGER NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL,
    PRIMARY KEY (content_hash, parser_sig)
);
CREATE INDEX ix_parse_cache_lru ON parse_cache(last_used_at);
""",
    ),
    (
        4,
        """
ALTER TABLE jobs ADD COLUMN progress TEXT;
ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;

CREATE TABLE ai_cache (
    cache_key TEXT PRIMARY KEY,
    answer_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_used_at REAL NOT NULL
);
CREATE INDEX ix_ai_cache_lru ON ai_cache(last_used_at);
""",
    ),
    (
        5,
        """
CREATE TABLE embedding_cache (
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (model, text_hash)
);
""",
    ),
    (
        6,
        """
ALTER TABLE chunks ADD COLUMN search_metadata TEXT NOT NULL DEFAULT '';
CREATE VIRTUAL TABLE chunks_meta_fts USING fts5(
    search_metadata, content='chunks', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER chunks_meta_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_meta_fts(rowid, search_metadata) VALUES (new.id, new.search_metadata);
END;
CREATE TRIGGER chunks_meta_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_meta_fts(chunks_meta_fts, rowid, search_metadata)
    VALUES ('delete', old.id, old.search_metadata);
END;
CREATE TRIGGER chunks_meta_au AFTER UPDATE OF search_metadata ON chunks BEGIN
    INSERT INTO chunks_meta_fts(chunks_meta_fts, rowid, search_metadata)
    VALUES ('delete', old.id, old.search_metadata);
    INSERT INTO chunks_meta_fts(rowid, search_metadata) VALUES (new.id, new.search_metadata);
END;
""",
    ),
    (
        7,
        """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE auth_sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_hash TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX ix_auth_sessions_expiry ON auth_sessions(expires_at);

CREATE TABLE auth_login_attempts (
    id INTEGER PRIMARY KEY,
    username_key TEXT NOT NULL,
    attempted_at REAL NOT NULL
);
CREATE INDEX ix_auth_login_attempts_user_time ON auth_login_attempts(username_key, attempted_at);

CREATE TABLE repository_access (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    granted_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, repo_id)
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_audit_events_created ON audit_events(created_at);

ALTER TABLE jobs ADD COLUMN owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
""",
    ),
    (
        8,
        """
ALTER TABLE users ADD COLUMN ai_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN ai_daily_limit INTEGER NOT NULL DEFAULT 0;
""",
    ),
]
