class ChatbotAPI {
  constructor() {
    this.baseURL = window.location.origin;
    this.isLoading = false;
    this.isUserScrolling = false;
    this.scrollTimeout = null;
    this.scrollbarTimeout = null;
    // Lưu chat_id cho phiên hiện tại; ưu tiên lấy lại từ sessionStorage để tránh mất khi reload tab
    this.chatId = window.sessionStorage.getItem('chat_id') || null;
    // Lưu lịch sử hội thoại trong một phiên (F5 là mất)
    this.history = [];
    this.init();
  }

  init() {
    this.checkConnection();
    this.setupEventListeners();
    this.setupScrollDetection();
    this.setupSwipeNavigation();
  }

  async checkConnection() {
    try {
      const response = await fetch(`${this.baseURL}/api/health`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      console.log('Connection status:', data);
    } catch (error) {
      console.error('Connection error:', error.message);
    }
  }

  setupEventListeners() {
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const chatInput = document.getElementById('chatInput');
    const chatSendButton = document.getElementById('chatSendButton');

    // Initial interface
    sendButton.addEventListener('click', () => this.sendMessage());
    messageInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !this.isLoading) {
        this.sendMessage();
      }
    });

    // Chat interface
    chatSendButton.addEventListener('click', () => this.sendChatMessage());
    chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !this.isLoading) {
        this.sendChatMessage();
      }
    });

    // Scroll to bottom button
    const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');
    scrollToBottomBtn.addEventListener('click', () => this.scrollToBottom(true));
  }

  setupScrollDetection() {
    const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');

    // Lắng nghe sự kiện cuộn của toàn bộ cửa sổ trình duyệt
    window.addEventListener('scroll', () => {
      this.isUserScrolling = true;
      
      // Clear existing timeout
      if (this.scrollTimeout) {
        clearTimeout(this.scrollTimeout);
      }

      // Set timeout để đánh dấu ngừng scroll
      this.scrollTimeout = setTimeout(() => {
        this.isUserScrolling = false;
      }, 1000);

      // Cập nhật hiển thị nút "Cuộn xuống dưới"
      this.updateScrollToBottomButton();
    });
  }

  updateScrollToBottomButton() {
    const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');
    if (!scrollToBottomBtn) return;
    const isAtBottom = (window.innerHeight + window.scrollY) >= document.documentElement.scrollHeight - 100;
    scrollToBottomBtn.style.display = isAtBottom ? 'none' : 'block';
  }

  scrollToBottom(smooth = false, force = false) {
    const scrollHeight = document.documentElement.scrollHeight;
    if (smooth) {
      window.scrollTo({ top: scrollHeight, behavior: 'smooth' });
    } else {
      window.scrollTo(0, scrollHeight);
    }
    setTimeout(() => this.updateScrollToBottomButton(), 100);
  }

  _appendHistory(role, content) {
    // Lưu lại lịch sử hội thoại, chỉ giữ khoảng 20 lượt gần nhất
    this.history.push({ role, content });
    if (this.history.length > 20) {
      this.history = this.history.slice(-20);
    }
  }

  async sendMessage() {
    if (this.isLoading) return;

    const messageInput = document.getElementById('messageInput');
    const message = messageInput.value.trim();

    if (!message) return;

    // Switch to chat interface
    this.switchToChatInterface();

    // Clear input and add user message
    messageInput.value = '';
    this.addMessage('user', message);

    // Show typing indicator
    this.showTypingIndicator();
    this.setLoading(true);

    try {
      await this.handleStreamingResponse(message);
    } catch (error) {
      this.addMessage('assistant', `Lỗi kết nối: ${error.message}`);
      this.scrollToBottom();
    } finally {
      this.hideTypingIndicator();
      this.setLoading(false);
      document.getElementById('chatInput').focus();
    }
  }

  async sendChatMessage() {
    if (this.isLoading) return;

    const chatInput = document.getElementById('chatInput');
    const message = chatInput.value.trim();

    if (!message) return;

    // Clear input and add user message
    chatInput.value = '';
    this.addMessage('user', message);

    // Show typing indicator
    this.showTypingIndicator();
    this.setLoading(true);

    try {
      await this.handleStreamingResponse(message);
    } catch (error) {
      this.addMessage('assistant', `Lỗi kết nối: ${error.message}`);
      this.scrollToBottom();
    } finally {
      this.hideTypingIndicator();
      this.setLoading(false);
      chatInput.focus();
    }
  }

  async handleStreamingResponse(message) {
    const response = await fetch(`${this.baseURL}/api/chat_stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history_cache: this.history,
        chat_id: this.chatId || undefined,
        use_citation_engine: true,
      })
    });

    if (!response.ok) throw new Error('Network response was not ok');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    let displayedText = "";
    let contexts = [];

    console.log("Starting stream consumption...");

    // Hide typing indicator immediately as we are about to show the streaming bubble
    this.hideTypingIndicator();

    // Create assistant message bubble upfront
    const messageObj = this.addMessage('assistant', '', [], true);
    const contentDiv = messageObj.contentDiv;

    // Typing queue processing
    let charQueue = [];
    let isTypingFinished = false;

    // Helper to apply formatting (markdown + citations) to partial text
    const formatText = (text, contexts) => {
      let result = text || "";
      // Remove [CLARIFY] early if present
      result = result.replace(/(\*\*)?\[CLARIFY\](\*\*)?/gi, "");

      // Sanitize: Remove any raw file paths hallucinated by the LLM
      result = result.replace(/(?:pre_pdf\/split_images\/|processed_data\/markdown\/)[^\s)\]]*/gi, "");

      // Replace [i], [[i]], [id: i] etc. with citation links - ALWAYS replace with [Ref]
      result = result.replace(/\[+?(?:id:\s?)?(\d+)\]+?/gi, (m, n) => {
        const idx = Number(n) - 1;
        if (Array.isArray(contexts) && idx >= 0 && idx < contexts.length) {
          const href = contexts[idx]?.source_image;
          return href ? `[\[Ref\]](${encodeURI(href)})` : `[Ref]`;
        }
        return `[Ref]`;
      });

      try {
        if (window.marked && result) {
          // Normalize newlines
          const normalized = result.replace(/\\n/g, '\n');
          let html = window.marked.parse(normalized);
          // Ensure links open in new tab
          return html.replace(/<a /g, '<a target="_blank" rel="noreferrer" ');
        }
        return result;
      } catch (e) {
        return result;
      }
    };

    // Separate loop for rendering to ensure consistent speed
    const renderLoop = async () => {
      while (!isTypingFinished || charQueue.length > 0) {
        if (charQueue.length > 0) {
          const char = charQueue.shift();
          displayedText += char;

          // Render markdown incrementally every few characters or on newline to be efficient
          // but actually doing it every char is fine for gpt-4o-mini length
          contentDiv.innerHTML = formatText(displayedText, contexts);

          this.scrollToBottom();
          await new Promise(r => setTimeout(r, 10));
        } else {
          // Wait a bit if queue is empty but stream is still active
          await new Promise(r => setTimeout(r, 30));
        }
      }
      // Final final render to be absolutely sure
      contentDiv.innerHTML = formatText(fullText, contexts);
      this.scrollToBottom();
    };

    renderLoop(); // Start render loop in background

    while (true) {
      try {
        const { done, value } = await reader.read();
        if (done) {
          console.log("Stream reader finished.");
          break;
        }

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (trimmedLine.startsWith('data: ')) {
            try {
              const data = JSON.parse(trimmedLine.replace(/^data: /, ''));
              if (data.error) {
                this.addMessage('assistant', `Lưu ý: ${data.error}`);
                isTypingFinished = true;
                return;
              }
              if (data.chunk) {
                fullText += data.chunk;
                charQueue.push(...data.chunk.split(''));
              }
              if (data.contexts) {
                contexts = data.contexts;
              }
              if (data.done) {
                this.chatId = data.chat_id;
                window.sessionStorage.setItem('chat_id', this.chatId);
              }
            } catch (e) {
              console.warn("Error parsing chunk:", e);
            }
          }
        }
      } catch (error) {
        console.error("Stream interrupted:", error);
        // Nếu ngắt kết nối nhưng đã có dữ liệu, coi như xong thay vì báo lỗi thô
        if (fullText.length > 0) {
          console.log("Partial content recovered.");
          break;
        } else {
          throw error;
        }
      }
    }

    isTypingFinished = true;

    // Wait for the render loop to exhaust the queue
    while (charQueue.length > 0) {
      await new Promise(r => setTimeout(r, 50));
    }

    // Finalize the message (history update, etc.)
    this.finalizeMessage(messageObj, fullText, contexts);
  }

  finalizeMessage(messageObj, content, contexts) {
    // The contentDiv rendering (markdown, citations, CLARIFY removal) is now handled
    // incrementally by the `formatText` helper in `handleStreamingResponse` and
    // a final render in the `renderLoop`.
    // This function now primarily handles history update and final scroll.

    // Update history
    this._appendHistory('assistant', {
      content: content,
      context_files: Array.from(new Set((contexts || []).map(c => c.filename).filter(Boolean))),
      context_categories: Array.from(new Set((contexts || []).map(c => c.category).filter(Boolean))),
    });

    this.scrollToBottom();
  }

  switchToChatInterface() {
    document.getElementById('initialInterface').style.display = 'none';
    document.getElementById('chatInterface').classList.add('active');
  }

  addMessage(sender, content, contexts = [], isStreaming = false) {
    const messagesContainer = document.getElementById('messages');

    // Remove initial AI message if it exists
    const initialMessage = messagesContainer.querySelector('.ai-message');
    if (initialMessage && messagesContainer.children.length === 1 && sender === 'user') {
      initialMessage.remove();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message-bubble ${sender === 'user' ? 'user-message' : 'ai-message'}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    let renderContent = content || '';
    // Xử lý assistant message: Thay thế toàn bộ [i], [1], [[1]]... thành [Ref]
    if (sender === 'assistant' && !isStreaming) {
      // Remove raw paths
      renderContent = renderContent.replace(/(?:pre_pdf\/split_images\/|processed_data\/markdown\/)[^\s)\]]*/gi, "");

      // Tuyệt đối chuyển [số] thành [Ref]
      renderContent = renderContent.replace(/\[+?(?:id:\s?)?(\d+)\]+?/gi, (m, n) => {
        const idx = Number(n) - 1;
        if (Array.isArray(contexts) && idx >= 0 && idx < contexts.length) {
          const href = contexts[idx]?.source_image;
          if (href) {
            return `[\[Ref\]](${encodeURI(href)})`;
          }
        }
        return `[Ref]`;
      });
    }

    if (sender === 'assistant' && !isStreaming) {
      // Render markdown -> HTML cho câu trả lời của AI
      try {
        if (window.marked) {
          // Chuyển chuỗi "\n" thành xuống dòng thực để ẩn ký tự \n và chỉ giữ layout
          const normalized = renderContent.replace(/\\n/g, '\n');
          contentDiv.innerHTML = window.marked.parse(normalized);
          // Ép mọi link mở tab mới
          contentDiv.querySelectorAll('a').forEach(a => {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noreferrer');
          });
        } else {
          contentDiv.textContent = renderContent;
        }
      } catch (e) {
        contentDiv.textContent = renderContent;
      }
    } else {
      contentDiv.textContent = renderContent;
    }

    messageDiv.appendChild(contentDiv);

    messagesContainer.appendChild(messageDiv);

    // (Ẩn block Nguồn tham khảo ngoài bubble; nguồn đã hiển thị bằng [i] trong nội dung)

    // Cập nhật lịch sử hội thoại cho LLM (user / assistant)
    if (!isStreaming) {
      if (sender === 'user') {
        this._appendHistory('user', content);
      } else {
        this._appendHistory('assistant', {
          content,
          context_files: Array.from(new Set((contexts || []).map(c => c.filename).filter(Boolean))),
          context_categories: Array.from(new Set((contexts || []).map(c => c.category).filter(Boolean))),
        });
      }
    }

    // Auto scroll to bottom - ensure new message is visible
    this.scrollToBottom();

    // Update scrollbar
    setTimeout(() => {
      const externalScrollbarThumb = document.querySelector('.external-scrollbar-thumb');
      if (externalScrollbarThumb) {
        const { scrollHeight, clientHeight } = messagesContainer;
        const thumbHeight = Math.max((clientHeight / scrollHeight) * 100, 10);
        externalScrollbarThumb.style.height = `${thumbHeight}%`;
      }
    }, 50);

    return { messageDiv, contentDiv };
  }

  showTypingIndicator() {
    const messagesContainer = document.getElementById('messages');

    // Remove existing typing indicator
    this.hideTypingIndicator();

    // Create typing message
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message-bubble typing-message';
    typingDiv.id = 'typingMessage';

    const dotsDiv = document.createElement('div');
    dotsDiv.className = 'flex items-center space-x-1';
    dotsDiv.innerHTML = `
      <div class="w-2 h-2 bg-blue-500 rounded-full animate-bounce"></div>
      <div class="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
      <div class="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
      <span class="ml-2 text-gray-600"></span>
    `;

    typingDiv.appendChild(dotsDiv);
    messagesContainer.appendChild(typingDiv);

    // Auto scroll to bottom - ensure typing indicator is visible
    this.scrollToBottom();
  }

  hideTypingIndicator() {
    const typingMessage = document.getElementById('typingMessage');
    if (typingMessage) {
      typingMessage.remove();
      // Auto scroll to bottom after removing typing indicator
      this.scrollToBottom();
    }
  }

  setLoading(loading) {
    this.isLoading = loading;
    const sendButton = document.getElementById('sendButton');
    const chatSendButton = document.getElementById('chatSendButton');
    const sendText = document.getElementById('sendText');
    const chatSendText = document.getElementById('chatSendText');

    if (loading) {
      if (sendButton) {
        sendButton.disabled = true;
        sendButton.className = 'bg-gray-400 cursor-not-allowed text-white rounded-full p-4 transition-all';
      }
      if (chatSendButton) {
        chatSendButton.disabled = true;
        chatSendButton.className = 'bg-gray-400 cursor-not-allowed text-white px-4 py-3 rounded-full';
      }
    } else {
      if (sendButton) {
        sendButton.disabled = false;
        sendButton.className = 'bg-blue-600 hover:bg-blue-700 text-white rounded-full p-4 transition-all';
        sendButton.textContent = '➤';
      }
      if (chatSendButton) {
        chatSendButton.disabled = false;
        chatSendButton.className = 'bg-blue-600 hover:bg-blue-700 text-white rounded-full p-4 transition-all';
        chatSendText.textContent = '➤';
      }
    }
  }

  setupSwipeNavigation() {
    // Để trình duyệt tự xử lý việc cuộn tự nhiên. 
    // Chúng ta chỉ cần đảm bảo thanh cuộn bên ngoài cập nhật theo.
    const messagesContainer = document.getElementById('messages');
    if (!messagesContainer) return;

    messagesContainer.addEventListener('scroll', () => {
      this.updateScrollToBottomButton();
    });
  }
}

// Global chatbot instance
let chatbotInstance = null;

// Initialize chatbot when page loads
document.addEventListener('DOMContentLoaded', () => {
  chatbotInstance = new ChatbotAPI();
});
