from typing import List, Dict
from rag.search.search import get_db_connection


def init_chat_history_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            chat_id VARCHAR(50) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def save_message(chat_id: str, role: str, content: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_history (chat_id, role, content) VALUES (%s, %s, %s)",
        (chat_id, role, content)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_chat_history(chat_id: str, limit: int = 10) -> List[Dict[str, str]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM chat_history WHERE chat_id = %s ORDER BY created_at DESC LIMIT %s",
        (chat_id, limit)
    )
    results = [{"role": row[0], "content": row[1]} for row in cur.fetchall()]
    cur.close()
    conn.close()
    return list(reversed(results))
