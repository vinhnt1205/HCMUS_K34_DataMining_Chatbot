import json
import os
import psycopg2
from typing import Any, Dict, List
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

def load_nodes_from_folder(folder_path: str) -> List[Dict[str, Any]]:
    nodes = []
    for filename in sorted(os.listdir(folder_path)):
        if filename.endswith(".json"):
            with open(os.path.join(folder_path, filename), "r", encoding = "utf-8") as f:
                node = json.load(f)
                nodes.append(node)
    return nodes

def create_table_and_import(nodes: List[Dict[str, Any]], table_name: str) -> None:
    conn_params = {
        "host": os.getenv("PG_HOST"),
        "port": os.getenv("PG_PORT"),
        "dbname": os.getenv("PG_DBNAME"),
        "user": os.getenv("PG_USER"),
        "password": os.getenv("PG_PASSWORD")
    }
    
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    node_id INTEGER,
                    content TEXT,
                    embedding VECTOR(3072),
                    metadata JSONB
                )
            """)
            
            for node in nodes:
                cur.execute(f"""
                    INSERT INTO {table_name} (node_id, content, embedding, metadata)
                    VALUES (%s, %s, %s, %s)
                """, (
                    node.get("id"),
                    node.get("text"),
                    node.get("embedding"),
                    json.dumps(node.get("metadata", {}))
                ))
            
            conn.commit()

if __name__ == "__main__":
    folder_path = "/Users/ntvinh120501/Documents/KHDL_K34/Data_Mining/rag/embedding/embedding_results/embedding_nodes"
    table_name = "stsv_embedding_nodes"
    nodes = load_nodes_from_folder(folder_path)
    create_table_and_import(nodes, table_name)

    print(f"Imported {len(nodes)} nodes to {table_name} table -> Done -> Pls check the database")

