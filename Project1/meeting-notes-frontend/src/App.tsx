import React, { useState, useEffect } from "react";
import axios from "axios";

// Types
interface Meeting {
  id: number;
  title: string;
  created_at: string;
}

function App() {
  const [transcript, setTranscript] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [currentSummary, setCurrentSummary] = useState<string>("");
  const [meetingId, setMeetingId] = useState<number | null>(null);
  const [query, setQuery] = useState<string>("");
  const [queryAnswer, setQueryAnswer] = useState<string>("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);

  // Fetch meetings history
  useEffect(() => {
    axios
      .get<Meeting[]>("http://localhost:8000/meetings")
      .then((res) => setMeetings(res.data))
      .catch((err) => console.error(err));
  }, [currentSummary]);

  // Submit transcript
  const handleTranscriptSubmit = async (
    e: React.FormEvent<HTMLFormElement>,
  ) => {
    e.preventDefault();
    if (!transcript) return;

    try {
      const res = await axios.post<{ id: number; summary: string }>(
        "http://localhost:8000/meetings",
        { transcript, title: title || "Untitled Meeting" },
      );
      setCurrentSummary(res.data.summary);
      setMeetingId(res.data.id);
      setTranscript("");
      setTitle("");
    } catch (err) {
      console.error(err);
    }
  };

  // Submit query
  const handleQuerySubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!query || !meetingId) return;

    try {
      const res = await axios.post<{ answer: string }>(
        `http://localhost:8000/meetings/${meetingId}/query`,
        { query },
      );
      setQueryAnswer(res.data.answer);
      setQuery("");
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ padding: "2rem", fontFamily: "Arial" }}>
      <h1>Meeting Notes App</h1>

      {/* Transcript Input */}
      <form onSubmit={handleTranscriptSubmit} style={{ marginBottom: "1rem" }}>
        <input
          type="text"
          placeholder="Meeting Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          style={{ width: "100%", marginBottom: "0.5rem", padding: "0.5rem" }}
        />
        <textarea
          placeholder="Paste meeting transcript here..."
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={10}
          style={{ width: "100%", marginBottom: "0.5rem", padding: "0.5rem" }}
        />
        <button type="submit" style={{ padding: "0.5rem 1rem" }}>
          Generate Notes
        </button>
      </form>

      {/* Summary Display */}
      {currentSummary && (
        <div style={{ marginBottom: "1rem" }}>
          <h2>Meeting Summary</h2>
          <pre style={{ background: "#f3f3f3", padding: "1rem" }}>
            {currentSummary}
          </pre>
        </div>
      )}

      {/* Query Input */}
      {currentSummary && (
        <form onSubmit={handleQuerySubmit} style={{ marginBottom: "1rem" }}>
          <input
            type="text"
            placeholder="Ask a question about the meeting..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: "80%", padding: "0.5rem" }}
          />
          <button
            type="submit"
            style={{ padding: "0.5rem 1rem", marginLeft: "0.5rem" }}
          >
            Query
          </button>
        </form>
      )}

      {/* Query Result */}
      {queryAnswer && (
        <div style={{ marginBottom: "1rem" }}>
          <h2>Query Result</h2>
          <p style={{ background: "#f9f9f9", padding: "1rem" }}>
            {queryAnswer}
          </p>
        </div>
      )}

      {/* Meeting History */}
      {meetings.length > 0 && (
        <div>
          <h2>Past Meetings</h2>
          <ul>
            {meetings.map((m) => (
              <li key={m.id}>
                {m.title} ({new Date(m.created_at).toLocaleString()})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default App;
