import os
import json
import uuid
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, request, Response, send_from_directory

from rag.search.search import get_nodes_from_db, prepare_documents, hybrid_search, rerank_search_cohere
from rag.prompt.prompt import build_prompt
from chat_history.chat_history import init_chat_history_table, save_message, get_chat_history

load_dotenv()

table_name = "stsv_embedding_nodes"
client = OpenAI(api_key = os.getenv("OPENAI_API_KEY"))
app = Flask(__name__, static_folder = "ui/chatbot/template")


def get_contexts(question: str, top_k: int = 20, top_n: int = 3):
    raw_nodes = get_nodes_from_db(table_name)
    docs = prepare_documents(raw_nodes)
    hybrid_results = hybrid_search(question, docs, table_name, top_k = top_k, weights = [0.2, 0.8])
    return rerank_search_cohere(question, hybrid_results, top_n = top_n)


def stream_response(question: str, chat_id: str):
    save_message(chat_id, "user", question)
    
    rerank_results = get_contexts(question)
    prompt = build_prompt(question, rerank_results)
    
    contexts = [
        {"id": doc.metadata.get("top_k"), "path": doc.metadata.get("path", "")}
        for doc in rerank_results
    ]
    
    yield f"data: {json.dumps({'contexts': contexts})}\n\n"
    
    stream = client.chat.completions.create(
        model = "gpt-4o-mini",
        messages = [{"role": "user", "content": prompt}],
        temperature = 0.1,
        stream = True
    )
    
    full_response = ""
    for chunk in stream:
        if chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            full_response += content
            yield f"data: {json.dumps({'chunk': content})}\n\n"
    
    save_message(chat_id, "assistant", full_response)
    yield f"data: {json.dumps({'done': True, 'chat_id': chat_id})}\n\n"


@app.route("/api/health")
def health():
    return {"status": "ok"}


@app.route("/api/chat_stream", methods = ["POST"])
def chat_stream():
    data = request.get_json()
    question = data.get("message", "")
    chat_id = data.get("chat_id")
    if not chat_id or chat_id == "undefined" or chat_id == "null":
        chat_id = str(uuid.uuid4())[:8]
    return Response(stream_response(question, chat_id), mimetype = "text/event-stream")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


if __name__ == "__main__":
    init_chat_history_table()
    app.run(host = "0.0.0.0", port = 8034, debug = True)
