I. Chi tiết từng bước (Step-by-Step)

    1. Xử lý dữ liệu
        - Thu thập dữ liệu (Input):
            + Đầu vào là file  "TSV2025_ONLINE.pdf" -> dùng pymupdf4llm để convert file .pdf thành file .md -> file "TSV2025_ONLINE.md"
            + Chuẩn hoá & check thủ công lại file "TSV2025_ONLINE.md" đã đúng/đủ thông tin so với file gốc chưa? Nếu chưa thì bổ sung thông tin cho hoàn chỉnh.

    2. Tổ chức & Chuẩn bị dữ liệu (Data Preparation & Chunking):
        - Bước 2a: Xây dựng cây phân cấp (Tree Construction)
            + Hệ thống đọc file Markdown và phân tích các thẻ Header (#, ##, **Chương**, **Điều**) để dựng lại cấu trúc phân cấp của văn bản gốc.
            + Dữ liệu được tổ chức dưới dạng cây (Json Tree): Root -> Chương -> Mục -> Điều.
            + Mục đích: Giữ lại ngữ cảnh (Context path) cho từng đoạn văn, ví dụ: "Chương I > Điều 5 > Quyền lợi sinh viên".

        - Bước 2b: Cắt nhỏ dữ liệu (Chunking Decision)
            + Hệ thống duyệt qua từng node trong cây.
            + Kiểm tra độ dài: Nếu nội dung node dài hơn 500 tokens, sử dụng thuật toán `RecursiveCharacterTextSplitter` để cắt nhỏ tiếp.
            + Tham số cắt: Chunk size = 500 tokens, Overlap = 100 tokens (để đảm bảo không bị mất thông tin ở điểm cắt).
            + Nếu node ngắn hơn 500 tokens: Giữ nguyên.

        - Bước 2c: Làm phẳng (Flattening)
            + Duỗi cây dữ liệu thành một danh sách phẳng (List of dictionary).
            + Mỗi phần tử chứa: Nội dung (text) + Metadata (Path, Token count).
            + Kết quả xuất ra file `stsv_flat.json`, sẵn sàng để gửi đi tạo Embedding.

    3. Mã hóa (Embedding):
        - Hệ thống đọc file JSON, gửi nội dung lên OpenAI, sử dụng model embedding = "text-embedding-3-large" để chuyển đổi thành các vector số học (3072 chiều).
        - Vector này đại diện cho ý nghĩa của đoạn văn bản.

    4. Lưu trữ (Indexing):
        - Database: PostgreSQL với extension `pgvector`.
        - Bảng lưu trữ (`stsv_embedding_nodes`) có cấu trúc gồm các trường chính:
            + `node_id`: ID định danh của đoạn văn.
            + `content`: Nội dung văn bản gốc (để trích xuất khi tìm thấy).
            + `embedding`: Vector 3072 chiều (kiểu dữ liệu `vector(3072)`).
            + `metadata`: JSON chứa thông tin bổ sung (Path, Token count, Level).

    5. Tìm kiếm & Truy xuất (Retrieval & Reranking):
        Quá trình tìm kiếm diễn ra qua 2 giai đoạn chính để đảm bảo độ chính xác cao nhất:

        a. Giai đoạn 1: Tìm kiếm Lai (Hybrid Search)
            - Hệ thống kết hợp 2 thuật toán tìm kiếm song song:
                + Semantic Search: Chuyển câu hỏi thành vector (OpenAI embedding) và tìm các đoạn văn có ý nghĩa tương đồng bằng khoảng cách Cosine trong PGVector.
                + Keyword Search (BM25): Tìm kiếm dựa trên sự trùng khớp từ khóa chính xác giữa câu hỏi và văn bản.
            - Cơ chế Lan truyền điểm (Hierarchical Boosting):
                + Hệ thống tận dụng cấu trúc cây (đã xây dựng ở bước 2).
                + Nếu một đoạn con khớp từ khóa/ý nghĩa, điểm số sẽ được cộng dồn (lan truyền) lên đoạn cha. Điều này giúp hệ thống ưu tiên các chương/mục có nội dung phù hợp về tổng thể.
            - Kết quả: Tổng hợp điểm số (tỷ trọng mặc định: 20% BM25 + 80% Semantic) để lấy ra Top 20 tài liệu tiềm năng nhất.

        b. Giai đoạn 2: Sắp xếp lại (Reranking)
            - Sử dụng model chuyên dụng Cohere Rerank (rerank-multilingual-v3.0).
            - Model này "đọc" trực tiếp câu hỏi và nội dung của Top 20 tài liệu trên để đánh giá lại độ phù hợp một cách chi tiết hơn.
            - Kết quả: Chọn ra 5 tài liệu tốt nhất (Top 5) để làm ngữ cảnh cho AI trả lời.
    
    6. Trả lời (Generation & Prompting):
        - Bước 6a: Xây dựng Prompt (Prompt Engineering)
            + Hệ thống đóng vai "Trợ lý ảo trường ĐH KHTN".
            + Ngữ cảnh (Context): Top 5 tài liệu tìm được được chèn vào prompt dưới dạng thẻ XML `<document>`.
            + Ràng buộc (Constraints):
                * Bắt buộc trích dẫn nguồn (path) cho mọi thông tin.
                * Nếu không có thông tin trong Context, phải trả lời "Thông tin này không có trong Sổ tay".
                * Không được bịa đặt thông tin.
        
        - Bước 6b: Gọi LLM
            + Gửi toàn bộ Prompt đã ghép Context tới API GPT-4o-mini. (dùng model LLM của OpenAO, model = "gpt-4o-mini")
            + Nhận câu trả lời dưới dạng Stream (trả về từng từ/token) để hiển thị mượt mà trên giao diện người dùng.

    7. Giao diện & Lưu trữ (UI & Archiving):
        - **Giao diện (Frontend):** 
            + Website đơn giản phục vụ HTML/CSS tĩnh từ thư mục `ui/chatbot/template/index.html`.
        
        - **Lưu trữ hội thoại (Chat History):**
            + Hệ thống tự động lưu toàn bộ câu hỏi của người dùng và câu trả lời của AI vào bảng `chat_history`.
            + Cấu trúc bảng `chat_history`:
                * `chat_id`: Mã phiên làm việc (Session ID).
                * `role`: 'user' hoặc 'assistant'.
                * `content`: Nội dung tin nhắn.
                * `created_at`: Thời gian tạo.
            + Lịch sử này được dùng để hiển thị lại đoạn chat cũ hoặc phục vụ phân tích sau này (nhưng hiện tại RAG chưa dùng lịch sử này làm context cho câu hỏi tiếp theo).
