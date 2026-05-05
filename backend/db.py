import sqlite3
from datetime import datetime
from config import DATABASE_PATH


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        customer_name TEXT DEFAULT '',
        customer_type TEXT DEFAULT '未知',
        status TEXT DEFAULT '进行中',
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer', 'assistant', 'system')),
        content TEXT NOT NULL,
        timestamp TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    );

    CREATE TABLE IF NOT EXISTS qa_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL UNIQUE,
        accuracy INTEGER CHECK(accuracy BETWEEN 1 AND 5),
        completeness INTEGER CHECK(completeness BETWEEN 1 AND 5),
        professionalism INTEGER CHECK(professionalism BETWEEN 1 AND 5),
        empathy INTEGER CHECK(empathy BETWEEN 1 AND 5),
        efficiency INTEGER CHECK(efficiency BETWEEN 1 AND 5),
        overall_score REAL,
        passed INTEGER DEFAULT 0,
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (message_id) REFERENCES messages(id)
    );

    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        company TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        frequency INTEGER DEFAULT 1,
        priority TEXT DEFAULT '中',
        status TEXT DEFAULT '待补充',
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS knowledge_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_type TEXT NOT NULL DEFAULT 'product',
        category TEXT DEFAULT '',
        title TEXT NOT NULL,
        brand TEXT DEFAULT '',
        spec TEXT DEFAULT '',
        unit TEXT DEFAULT '',
        list_price REAL,
        wholesale_price REAL,
        wholesale_condition TEXT DEFAULT '',
        core_params TEXT DEFAULT '',
        usage_scenarios TEXT DEFAULT '',
        related_items TEXT DEFAULT '',
        question TEXT DEFAULT '',
        answer TEXT DEFAULT '',
        policy_scope TEXT DEFAULT '',
        policy_rule TEXT DEFAULT '',
        policy_timeframe TEXT DEFAULT '',
        policy_note TEXT DEFAULT '',
        lifecycle_status TEXT DEFAULT 'active',
        publish_status TEXT DEFAULT 'draft',
        sync_status TEXT DEFAULT 'pending',
        dify_dataset_id TEXT,
        dify_document_id TEXT,
        last_sync_error TEXT,
        last_synced_at TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS knowledge_item_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_item_id INTEGER NOT NULL,
        version_number INTEGER NOT NULL,
        snapshot TEXT NOT NULL,
        change_note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (knowledge_item_id) REFERENCES knowledge_items(id)
    );

    CREATE TABLE IF NOT EXISTS knowledge_sync_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_item_id INTEGER NOT NULL,
        provider TEXT DEFAULT 'dify',
        operation TEXT DEFAULT 'upsert',
        status TEXT DEFAULT 'pending',
        request_payload TEXT DEFAULT '{}',
        response_payload TEXT DEFAULT '{}',
        error TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (knowledge_item_id) REFERENCES knowledge_items(id)
    );
    """)
    conn.close()


# ── conversations ──

def get_conversations():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id):
    conn = get_db()
    conv = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if not conv:
        conn.close()
        return None
    messages = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp",
        (conv_id,),
    ).fetchall()
    conn.close()
    return {**dict(conv), "messages": [dict(m) for m in messages]}


def create_conversation(session_id, customer_name="", customer_type="未知"):
    conn = get_db()
    conn.execute(
        "INSERT INTO conversations (session_id, customer_name, customer_type) VALUES (?, ?, ?)",
        (session_id, customer_name, customer_type),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM conversations WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def update_conversation_status(conv_id, status):
    conn = get_db()
    conn.execute(
        "UPDATE conversations SET status = ? WHERE id = ?", (status, conv_id)
    )
    conn.commit()
    conn.close()


# ── messages ──

def add_message(conversation_id, role, content):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
        (conversation_id, role, content),
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return msg_id


# ── qa_results ──

def save_qa_result(message_id, scores: dict):
    conn = get_db()
    overall = (
        scores["accuracy"]
        + scores["completeness"]
        + scores["professionalism"]
        + scores["empathy"]
        + scores["efficiency"]
    ) / 5.0
    dims = [scores["accuracy"], scores["completeness"], scores["professionalism"],
            scores["empathy"], scores["efficiency"]]
    passed = 1 if all(v >= 3 for v in dims) else 0
    conn.execute(
        """INSERT OR REPLACE INTO qa_results
           (message_id, accuracy, completeness, professionalism, empathy, efficiency,
            overall_score, passed, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message_id,
            scores["accuracy"],
            scores["completeness"],
            scores["professionalism"],
            scores["empathy"],
            scores["efficiency"],
            round(overall, 2),
            passed,
            scores.get("reason", ""),
        ),
    )
    conn.commit()
    conn.close()


# ── knowledge_gaps ──

def get_knowledge_gaps():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM knowledge_gaps ORDER BY frequency DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_knowledge_gap(question, priority="中"):
    conn = get_db()
    existing = conn.execute(
        "SELECT id, frequency FROM knowledge_gaps WHERE question = ?", (question,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE knowledge_gaps SET frequency = frequency + 1 WHERE id = ?",
            (existing["id"],),
        )
    else:
        conn.execute(
            "INSERT INTO knowledge_gaps (question, priority) VALUES (?, ?)",
            (question, priority),
        )
    conn.commit()
    conn.close()


def update_knowledge_gap(gap_id, updates):
    allowed = {"status", "priority"}
    payload = {key: value for key, value in updates.items() if key in allowed}
    conn = get_db()
    if payload:
        assignments = ", ".join(f"{key} = ?" for key in payload)
        values = list(payload.values()) + [gap_id]
        conn.execute(f"UPDATE knowledge_gaps SET {assignments} WHERE id = ?", values)
        conn.commit()
    row = conn.execute("SELECT * FROM knowledge_gaps WHERE id = ?", (gap_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}
