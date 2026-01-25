import json, tiktoken, re
from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter

config = {
    "input": "input_data/STSV2025_ONLINE.md",
    "output_tree": "json_folder/stsv_tree.json",
    "output_flat": "json_folder/stsv_flat.json",
    "model": "cl100k_base",
    "max_tokens": 500,
    "overlap": 100
}

def identify_header(line: str) -> Dict:
    line = line.strip()
    if not line: return None
    if m := re.match(r'^(#{1,6})\s+(.*)', line):
        return {"level": len(m.group(1)), "title": m.group(2).strip().replace("**", "")}
    if re.match(r'^\*\*[A-ZÀÁẠẢÃÈÉẸẺẼÌÍỊỈĨÒÓỌỎÕÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ\s]{10,}\*\*$', line):
        title = line.replace("**", "").strip()
        if "Col" not in title: return {"level": 1, "title": title}
    if re.match(r'^(\*\*|)(Chương\s+[IVX\d]+(\.|\:)?.*?)(\*\*|)$', line, re.I):
        return {"level": 2, "title": line.replace("**", "").strip()}
    if re.match(r'^(\*\*|)([IVX]+\.\s+[A-ZÀÁẠẢÃÈÉẸẺẼÌÍỊỈĨÒÓỌỎÕÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ\s]+)(\*\*|)$', line):
        return {"level": 2, "title": line.replace("**", "").strip()}
    if re.match(r'^(\*\*|)(Điều\s+\d+(\.|\:)?.*?)(\*\*|)$', line, re.I):
        return {"level": 3, "title": line.replace("**", "").strip()}
    return None

def build_tree():
    encoding = tiktoken.get_encoding(config["model"])
    with open(config["input"], "r", encoding="utf-8") as f:
        lines = f.readlines()

    root = {"title": "Root", "level": 0, "content": "", "metadata": {"path": "Root"}, "children": []}
    stack, current_content = [root], []

    def flush():
        if current_content:
            stack[-1]["content"] = (stack[-1].get("content", "") + "\n" + "".join(current_content)).strip()
            current_content.clear()

    for line in lines:
        if h := identify_header(line):
            flush()
            while len(stack) > 1 and stack[-1]["level"] >= h["level"]: stack.pop()
            node = {
                "title": h["title"], "level": h["level"], "content": line.strip(),
                "metadata": {"path": f"{stack[-1]['metadata']['path']} > {h['title']}"},
                "children": []
            }
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            current_content.append(line)
    flush()

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name = config["model"], 
        chunk_size = config["max_tokens"], 
        chunk_overlap = config["overlap"]
    )

    def finalize(n):
        raw_lines = n["content"].split('\n')
        n["content"] = '\n'.join([l for l in raw_lines if not re.match(r'^\d+$', l.strip())]).strip()
        n["token_count"] = len(encoding.encode(n["content"]))
        
        if n["token_count"] > config["max_tokens"]:
            chunks = splitter.split_text(n["content"])
            if len(chunks) > 1:
                for i, chunk in enumerate(chunks):
                    n["children"].append({
                        "title": f"Part {i+1}", "level": n["level"] + 1, "content": chunk,
                        "token_count": len(encoding.encode(chunk)),
                        "metadata": {"path": f"{n['metadata']['path']} > Part {i+1}"},
                        "children": []
                    })
                n["content"] = f"Split into {len(chunks)} parts"
                n["token_count"] = len(encoding.encode(n["content"]))
        
        for c in n["children"]: finalize(c)

    finalize(root)
    with open(config["output_tree"], "w", encoding = "utf-8") as f:
        json.dump(root, f, ensure_ascii = False, indent = 2)
    return root

def flatten_and_save(tree):
    flat = []
    def walk(n):
        
        if n["content"] and not (n["content"].startswith("Split into") and "parts" in n["content"]):
            
            node_data = {
                "content": n["content"],
                "token_count": n["token_count"],
                "metadata": {**n["metadata"], "token_count": n["token_count"]}
            }
            flat.append(node_data)
        for c in n["children"]: walk(c)
    
    walk(tree)
    with open(config["output_flat"], "w", encoding = "utf-8") as f:
        json.dump(flat, f, ensure_ascii = False, indent = 2)
    
    total_tokens = sum(item["token_count"] for item in flat)
    print(f"Total of tokens: {total_tokens}")
    print(f"Total of chunks): {len(flat)}")

if __name__ == "__main__":
    flatten_and_save(build_tree())
