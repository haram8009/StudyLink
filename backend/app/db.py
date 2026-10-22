"""SQLite connections are short lived; external requests run outside transactions."""
from contextlib import contextmanager
import sqlite3
from uuid import NAMESPACE_URL, uuid5
from .config import get_settings

@contextmanager
def get_connection():
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA busy_timeout=10000')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS workspaces (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), filename TEXT NOT NULL,
 path TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('processing','ready','failed')), error TEXT);
CREATE INDEX IF NOT EXISTS documents_workspace ON documents(workspace_id);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, source_type TEXT NOT NULL CHECK(source_type IN ('doc','note')), source_id TEXT NOT NULL,
 page INTEGER, text TEXT NOT NULL, embedding BLOB NOT NULL, embedding_model TEXT NOT NULL, embedding_dim INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_type,source_id);
CREATE TABLE IF NOT EXISTS notes (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
 index_status TEXT NOT NULL CHECK(index_status IN ('ok','failed')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_notes (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id), note_id TEXT NOT NULL REFERENCES notes(id),
 PRIMARY KEY(workspace_id,note_id));
CREATE INDEX IF NOT EXISTS workspace_notes_workspace ON workspace_notes(workspace_id);
CREATE TABLE IF NOT EXISTS note_citations (
 note_id TEXT NOT NULL REFERENCES notes(id), citation_id TEXT NOT NULL,
 source_type TEXT NOT NULL CHECK(source_type IN ('doc','note')), document_id TEXT REFERENCES documents(id),
 page INTEGER, quote TEXT, cited_note_id TEXT, PRIMARY KEY(note_id,citation_id));
CREATE TABLE IF NOT EXISTS chats (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), title TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chats_workspace ON chats(workspace_id,updated_at);
CREATE TABLE IF NOT EXISTS answers (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), question TEXT NOT NULL,
 body_json TEXT NOT NULL, created_at TEXT NOT NULL, chat_id TEXT REFERENCES chats(id));
CREATE TABLE IF NOT EXISTS quizzes (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), requested_count INTEGER NOT NULL,
 actual_count INTEGER NOT NULL, created_at TEXT NOT NULL, submitted_at TEXT);
CREATE TABLE IF NOT EXISTS questions (
 id TEXT PRIMARY KEY, quiz_id TEXT NOT NULL REFERENCES quizzes(id), stem TEXT NOT NULL, options_json TEXT NOT NULL,
 answer_option_id TEXT NOT NULL, explanation TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id), page INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id), selected_option_id TEXT NOT NULL,
 correct INTEGER NOT NULL CHECK(correct IN (0,1)), submitted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
 id TEXT PRIMARY KEY, question_id TEXT NOT NULL UNIQUE REFERENCES questions(id),
 status TEXT NOT NULL CHECK(status IN ('open','reviewed')), learner_reason TEXT NOT NULL DEFAULT '');
'''

LEGACY_CHAT_TITLE = '이전 대화'

def legacy_chat_id(workspace_id: str) -> str:
    """Deterministic id so repeated migrations reuse the same chat."""
    return str(uuid5(NAMESPACE_URL, f'studylink:legacy-chat:{workspace_id}'))

def init_db():
    with get_connection() as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.executescript(SCHEMA)
    with get_connection() as connection:
        _migrate_answers_to_chats(connection)
    with get_connection() as connection:
        _migrate_quiz_tables(connection)

def _migrate_answers_to_chats(connection):
    """Day-one databases lack answers.chat_id; move unassigned answers into one legacy chat per workspace."""
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(answers)')}
    if 'chat_id' not in columns:
        connection.execute('ALTER TABLE answers ADD COLUMN chat_id TEXT REFERENCES chats(id)')
    connection.execute('CREATE INDEX IF NOT EXISTS answers_chat ON answers(chat_id,created_at)')
    connection.execute('CREATE INDEX IF NOT EXISTS answers_workspace ON answers(workspace_id,created_at)')
    pending = connection.execute('''SELECT workspace_id, MIN(created_at) AS first, MAX(created_at) AS last
        FROM answers WHERE chat_id IS NULL GROUP BY workspace_id''').fetchall()
    for row in pending:
        chat_id = legacy_chat_id(row['workspace_id'])
        connection.execute('INSERT OR IGNORE INTO chats(id,workspace_id,title,created_at,updated_at) VALUES (?,?,?,?,?)',
                           (chat_id, row['workspace_id'], LEGACY_CHAT_TITLE, row['first'], row['last']))
        connection.execute('UPDATE answers SET chat_id=? WHERE workspace_id=? AND chat_id IS NULL', (chat_id, row['workspace_id']))
        connection.execute('UPDATE chats SET updated_at=MAX(updated_at,?) WHERE id=?', (row['last'], chat_id))

def _migrate_quiz_tables(connection):
    """Day-three: questions keep the evidence quote and chunk id; lookup indexes for quizzes/reviews."""
    quiz_columns = {row['name'] for row in connection.execute('PRAGMA table_info(quizzes)')}
    if 'difficulty' not in quiz_columns:
        connection.execute("ALTER TABLE quizzes ADD COLUMN difficulty TEXT CHECK(difficulty IN ('easy','medium','hard'))")
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(questions)')}
    if 'quote' not in columns:
        connection.execute('ALTER TABLE questions ADD COLUMN quote TEXT')
    if 'chunk_id' not in columns:
        connection.execute('ALTER TABLE questions ADD COLUMN chunk_id TEXT')
    connection.execute('CREATE INDEX IF NOT EXISTS questions_quiz ON questions(quiz_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS quizzes_workspace ON quizzes(workspace_id,created_at)')
    connection.execute('CREATE INDEX IF NOT EXISTS attempts_question ON attempts(question_id)')

def recover_interrupted_documents():
    with get_connection() as connection:
        connection.execute("DELETE FROM chunks WHERE source_type='doc' AND source_id IN (SELECT id FROM documents WHERE status='processing')")
        connection.execute("UPDATE documents SET status='failed',error='서버 재시작으로 중단' WHERE status='processing'")
