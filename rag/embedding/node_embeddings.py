import json, os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

embeddings_model = OpenAIEmbeddings(
    model = "text-embedding-3-large",
    openai_api_key = os.getenv("OPENAI_API_KEY")
)

def get_embeddings(input_file, output_dir):
    with open(input_file, "r", encoding = "utf-8") as f:
        data = json.load(f)

    texts = [item["content"] for item in data]
    embeddings = embeddings_model.embed_documents(texts)

    nodes_dir = os.path.join(output_dir, "nodes")
    os.makedirs(nodes_dir, exist_ok = True)

    all_nodes = []
    for i, (item, embedding) in enumerate(zip(data, embeddings)):
        node_data = {
            "id": i,
            "text": item["content"],
            "embedding": embedding,
            "metadata": item.get("metadata", {})
        }
        all_nodes.append(node_data)
        
        node_file = os.path.join(nodes_dir, f"node_{i:04d}.json")
        with open(node_file, "w", encoding = "utf-8") as f:
            json.dump(node_data, f, ensure_ascii = False, indent = 2)

    summary_file = os.path.join(output_dir, "data_embeddings.json")
    with open(summary_file, "w", encoding = "utf-8") as f:
        json.dump(all_nodes, f, ensure_ascii = False, indent = 2)

    print(f"Saved {len(all_nodes)} nodes to directory: {nodes_dir}")

if __name__ == "__main__":
    get_embeddings("json_folder/stsv_flat.json", "rag/embedding/embedding_results")
