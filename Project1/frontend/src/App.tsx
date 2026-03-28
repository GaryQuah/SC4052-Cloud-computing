import { useState } from "react";
import { Modal, Button, Form } from "react-bootstrap";
import "bootstrap/dist/css/bootstrap.min.css";

type Message = { type: "user" | "bot"; text: string };
type HistoryMessage = { role: "user" | "assistant"; content: string };

function App() {
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [history, setHistory] = useState<HistoryMessage[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);

  const handleQuery = async () => {
    if (!query.trim()) return;

    const userText = query;
    const newMessages: Message[] = [
      ...messages,
      { type: "user", text: userText },
    ];
    setMessages(newMessages);
    setQuery("");
    setLoading(true);

    const res = await fetch("http://localhost:8000/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: userText, history }),
    });

    const data = await res.json();
    const botText: string = data.answer;

    setMessages([...newMessages, { type: "bot", text: botText }]);

    // Append this turn to history so the next query has full context
    setHistory([
      ...history,
      { role: "user", content: userText },
      { role: "assistant", content: botText },
    ]);

    setLoading(false);
  };

  const handleClearContext = () => {
    setMessages([]);
    setHistory([]);
  };

  const handleUpload = async () => {
    await fetch("http://localhost:8000/load-meetings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    });
    setShowModal(false);
    setNotes("");
  };

  const handleReload = async () => {
    await fetch("http://localhost:8000/load-meetings", { method: "POST" });
    alert("Reloaded!");
  };

  return (
    <div className="container d-flex justify-content-center align-items-center vh-100">
      <div style={{ maxWidth: "600px", width: "100%" }}>
        {/* Header */}
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h2 className="m-0">Meeting Query</h2>
          {messages.length > 0 && (
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={handleClearContext}
              title="Clear conversation and start a new topic"
            >
              New Topic
            </Button>
          )}
        </div>

        {/* Chat window */}
        <div
          className="d-flex flex-column border p-3 mb-3"
          style={{ height: "400px", overflowY: "auto" }}
        >
          {messages.length === 0 && (
            <p className="text-muted text-center m-auto">
              Ask a question about your meetings.
            </p>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`d-flex ${
                msg.type === "user"
                  ? "justify-content-end"
                  : "justify-content-start"
              }`}
            >
              <div
                className={`p-2 m-1 rounded ${
                  msg.type === "user" ? "bg-primary text-white" : "bg-light"
                }`}
                style={{
                  maxWidth: "70%",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {msg.text}
              </div>
            </div>
          ))}

          {loading && (
            <div className="d-flex justify-content-start">
              <div className="p-2 m-1 rounded bg-light text-muted fst-italic">
                Thinking…
              </div>
            </div>
          )}
        </div>

        {/* Input bar */}
        <div className="d-flex gap-2">
          <input
            className="form-control"
            value={query}
            placeholder="Ask about your meetings…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !loading && handleQuery()}
            disabled={loading}
          />
          <Button onClick={handleQuery} disabled={loading}>
            Send
          </Button>
          <Button onClick={() => setShowModal(true)} disabled={loading}>
            Upload
          </Button>
          <Button variant="secondary" onClick={handleReload} disabled={loading}>
            Reload
          </Button>
        </div>
      </div>

      {/* Upload modal */}
      <Modal show={showModal} onHide={() => setShowModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Upload Meeting Notes</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Control
            as="textarea"
            rows={8}
            placeholder="Paste meeting notes here…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleUpload}>Submit</Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}

export default App;
