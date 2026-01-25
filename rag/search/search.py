import os
import psycopg2
import numpy as np
import re
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
import cohere

load_dotenv()


def get_db_connection():
    return psycopg2.connect(
        host = os.getenv("PG_HOST"),
        port = os.getenv("PG_PORT"),
        dbname = os.getenv("PG_DBNAME"),
        user = os.getenv("PG_USER"),
        password = os.getenv("PG_PASSWORD")
    )


def get_nodes_from_db(table_name: str) -> list:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT node_id, content, embedding, metadata FROM {table_name} ORDER BY node_id")
    
    results = [
        {"node_id": row[0], 
        "content": row[1], 
        "embedding": np.array(row[2]), 
        "metadata": row[3]}
        for row in cur.fetchall()
    ]
    
    cur.close()
    conn.close()
    return results


def preprocess_text(text: str) -> str:
    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+', text)
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    
    url_map = {url: f"URL{i}" for i, url in enumerate(urls)}
    email_map = {email: f"EMAIL{i}" for i, email in enumerate(emails)}
    
    for url, placeholder in url_map.items():
        text = text.replace(url, placeholder)
    for email, placeholder in email_map.items():
        text = text.replace(email, placeholder)
    
    text = re.sub(r'(\w+)/(\w+)', r'\1 \2', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\b[A-Z]\.\s*', lambda m: m.group().lower().replace('.', ''), text)
    
    words = text.split()
    vietnamese_words = []
    english_words = []
    
    for word in words:
        if re.match(r'^[a-zA-Z]+$', word) and len(word) > 2:
            if word.upper() in ['PSG', 'GS', 'THS', 'TS', 'PGS']:
                continue
            english_words.append(word)
        elif re.match(r'^\d+$', word) and len(word) < 3:
            continue
        else:
            vietnamese_words.append(word)
    
    processed_text = ' '.join(vietnamese_words + english_words)
    processed_text = re.sub(r'\s+', ' ', processed_text).strip().lower()
    
    for placeholder, url in url_map.items():
        processed_text = processed_text.replace(placeholder.lower(), url)
    for placeholder, email in email_map.items():
        processed_text = processed_text.replace(placeholder.lower(), email)
    
    return processed_text


def prepare_documents(raw_nodes: list) -> List[Document]:
    results = [
        Document(
            page_content = node["content"], 
            metadata = {**node["metadata"], 
                        "node_id": node["node_id"]})
        for node in raw_nodes
    ]
    return results


def semantic_search(query: str, table_name: str, top_k: int) -> List[Document]:
    embeddings = OpenAIEmbeddings(
        openai_api_key = os.getenv("OPENAI_API_KEY"), 
        model = "text-embedding-3-large")
    query_embedding = embeddings.embed_query(query)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT node_id, content, metadata, 1 - (embedding <=> %s::vector) as similarity
        FROM {table_name}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (query_embedding, query_embedding, top_k))
    
    results = [
        Document(
            page_content = row[1], 
            metadata = {**row[2], 
                        "node_id": row[0], 
                        "similarity_score": float(row[3])})
        for row in cur.fetchall()
    ]
    
    cur.close()
    conn.close()
    return results


def bm25_search(query: str, docs: List[Document], top_k: int) -> List[Document]:
    retriever = BM25Retriever.from_documents(docs)
    retriever.k = top_k
    return retriever.invoke(query)


def hybrid_search(query: str, docs: List[Document], table_name: str, top_k: int, weights: List[float] = None, decay: float = 0.8) -> List[Document]:
    if weights is None:
        weights = [0.5, 0.5]
    bm25_weight, semantic_weight = weights

    tree = {"children": {}, "node_ids": []}
    for doc in docs:
        path = doc.metadata.get("path", "Root")
        node_id = doc.metadata.get("node_id")
        current = tree
        for part in [p.strip() for p in path.split(">")]:
            if part not in current["children"]:
                current["children"][part] = {"children": {}, "node_ids": []}
            current = current["children"][part]
        current["node_ids"].append(node_id)

    leaf_ids = set()
    stack = [tree]
    while stack:
        node = stack.pop()
        if not node["children"]:
            leaf_ids.update(node["node_ids"])
        else:
            stack.extend(node["children"].values())

    bm25_results = bm25_search(query, docs, len(docs))
    bm25_scores = {d.metadata.get("node_id"): 1.0 - (i / len(bm25_results)) for i, d in enumerate(bm25_results)}

    propagated_bm25 = {}
    stack = [(tree, 0.0)]
    while stack:
        node, inherited = stack.pop()
        current_max = max((bm25_scores.get(nid, 0.0) for nid in node["node_ids"]), default = 0.0)
        for nid in node["node_ids"]:
            propagated_bm25[nid] = bm25_scores.get(nid, 0.0) + inherited
        for c in node["children"].values():
            stack.append((c, (inherited + current_max) * decay))

    semantic_results = semantic_search(query, table_name, len(leaf_ids))
    semantic_scores = {d.metadata.get("node_id"): d.metadata.get("similarity_score", 0.0) 
                       for d in semantic_results if d.metadata.get("node_id") in leaf_ids}

    leaf_bm25 = {k: v for k, v in propagated_bm25.items() if k in leaf_ids}
    bm25_vals = list(leaf_bm25.values())
    sem_vals = list(semantic_scores.values())
    bm25_min, bm25_max = (min(bm25_vals), max(bm25_vals)) if bm25_vals else (0, 1)
    sem_min, sem_max = (min(sem_vals), max(sem_vals)) if sem_vals else (0, 1)

    results = []
    doc_map = {d.metadata.get("node_id"): d for d in docs}
    final_scores = {}
    for nid in leaf_ids:
        b = (leaf_bm25.get(nid, 0) - bm25_min) / (bm25_max - bm25_min) if bm25_max != bm25_min else 1.0
        s = (semantic_scores.get(nid, 0) - sem_min) / (sem_max - sem_min) if sem_max != sem_min else 1.0
        final_scores[nid] = bm25_weight * b + semantic_weight * s

    for i, nid in enumerate(sorted(final_scores, key = final_scores.get, reverse = True)[:top_k]):
        doc = doc_map.get(nid)
        if doc:
            doc.metadata["bm25_score"] = (leaf_bm25.get(nid, 0) - bm25_min) / (bm25_max - bm25_min) if bm25_max != bm25_min else 1.0
            doc.metadata["semantic_score"] = (semantic_scores.get(nid, 0) - sem_min) / (sem_max - sem_min) if sem_max != sem_min else 1.0
            doc.metadata["final_score"] = final_scores[nid]
            doc.metadata["top_k"] = i + 1
            results.append(doc)

    return results


def rerank_search_cohere(query: str, hybrid_results: List[Document], top_n: int, rerank_weight: float = 0.4) -> List[Document]:
    client = cohere.Client(api_key = os.getenv("COHERE_API_KEY"))
    docs_text = [doc.page_content for doc in hybrid_results]
    response = client.rerank(
        model = "rerank-multilingual-v3.0",
        query = query,
        documents = docs_text,
        top_n = len(hybrid_results)
    )
    
    rerank_scores = {item.index: float(item.relevance_score) for item in response.results}
    rr_vals = list(rerank_scores.values())
    rr_min, rr_max = (min(rr_vals), max(rr_vals)) if rr_vals else (0, 1)
    
    combined = []
    for i, doc in enumerate(hybrid_results):
        hybrid_score = doc.metadata.get("final_score", 0)
        raw_rerank = rerank_scores.get(i, 0)
        norm_rerank = (raw_rerank - rr_min) / (rr_max - rr_min) if rr_max != rr_min else 1.0
        combined_score = (1 - rerank_weight) * hybrid_score + rerank_weight * norm_rerank
        doc.metadata["rerank_score"] = raw_rerank
        doc.metadata["combined_score"] = combined_score
        combined.append((combined_score, doc))
    
    combined.sort(key = lambda x: x[0], reverse = True)
    results = []
    for i, (score, doc) in enumerate(combined[:top_n]):
        doc.metadata["top_k"] = i + 1
        results.append(doc)
    return results


# if __name__ == "__main__":
#     query = "cơ hội việc làm ngành toán học"
#     table_name = "stsv_embedding_nodes"
#     raw_nodes = get_nodes_from_db(table_name)
#     docs = prepare_documents(raw_nodes)
#     hybrid_results = hybrid_search(query, docs, table_name, top_k = 20, weights = [0.2, 0.8], decay = 0.8)
#     rerank_results = rerank_search_cohere(query, hybrid_results, top_n = 5, rerank_weight = 0.2)
#     for doc in rerank_results:
#         print(f"\n{'='*60}")
#         print(f"Top {doc.metadata['top_k']}")
#         print(f"{'='*60}")
#         print(f"Node ID: {doc.metadata.get('node_id')}")
#         print(f"Path: {doc.metadata.get('path', '')}")
#         print(f"BM25 Score: {doc.metadata.get('bm25_score', 0):.4f}")
#         print(f"Semantic Score: {doc.metadata.get('semantic_score', 0):.4f}")
#         print(f"Hybrid Score: {doc.metadata.get('final_score', 0):.4f}")
#         print(f"Rerank Score: {doc.metadata.get('rerank_score', 0):.4f}")
#         print(f"Combined Score: {doc.metadata.get('combined_score', 0):.4f}")
#         print(f"Content:\n{doc.page_content}")