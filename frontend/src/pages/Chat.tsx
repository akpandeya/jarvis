import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";
import { useChatStream } from "../hooks/useChatStream";
import type { ChatSessionMeta } from "../lib/types";

const emptyMeta: ChatSessionMeta = {
  session_id: "",
  history_preview: "",
  history: [],
  autostart_prompt: "",
  autostart_model: "",
};

export default function Chat() {
  const [params, setParams] = useSearchParams();
  const sessionParam = params.get("session") ?? "";
  const autostart = params.get("autostart") === "1";

  const { data: meta = emptyMeta } = useQuery({
    queryKey: keys.chatSession(sessionParam),
    queryFn: () => api.chatSession(sessionParam),
    enabled: !!sessionParam,
    staleTime: Infinity,
  });

  const { state, send, resetSession } = useChatStream({
    messages: meta.history.map((h) => ({ role: h.role, text: h.text })),
    sessionId: meta.session_id || null,
  });

  const [input, setInput] = useState("");
  const outputRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const autostartFired = useRef(false);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [state.messages]);

  // Sync URL once we receive a session_id
  useEffect(() => {
    if (state.sessionId && state.sessionId !== sessionParam) {
      const p = new URLSearchParams(params);
      p.set("session", state.sessionId);
      p.delete("autostart");
      setParams(p, { replace: true });
    }
  }, [state.sessionId, sessionParam, params, setParams]);

  // Autostart review prompt if redirected from PRs
  useEffect(() => {
    if (autostart && meta.autostart_prompt && !autostartFired.current) {
      autostartFired.current = true;
      void send(meta.autostart_prompt, {
        model: meta.autostart_model || undefined,
        displayAs: "(PR review request)",
      });
    }
  }, [autostart, meta.autostart_prompt, meta.autostart_model, send]);

  const handleSend = async () => {
    if (!input.trim() || state.sending) return;
    const m = input;
    setInput("");
    await send(m);
    inputRef.current?.focus();
  };

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 style={{ margin: 0 }}>Chat with Claude</h2>
        <button
          onClick={() => {
            resetSession();
            setParams({}, { replace: true });
          }}
          style={{
            fontSize: "0.75rem",
            padding: "0.25rem 0.75rem",
            border: "1px solid var(--color-muted)",
            borderRadius: 4,
            background: "none",
            color: "var(--color-muted)",
          }}
        >
          + New conversation
        </button>
      </div>

      {meta.history_preview && (
        <aside
          style={{
            borderLeft: "3px solid var(--color-primary)",
            padding: "0.5rem 1rem",
            marginBottom: "1rem",
            fontSize: "0.9em",
            color: "var(--color-muted)",
          }}
        >
          Resuming: <strong style={{ color: "var(--color-text)" }}>{meta.history_preview.slice(0, 120)}</strong>
        </aside>
      )}

      <div
        ref={outputRef}
        style={{
          minHeight: 200,
          maxHeight: "60vh",
          overflowY: "auto",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          padding: "1rem",
          marginBottom: "1rem",
          whiteSpace: "pre-wrap",
          fontSize: "0.9em",
          lineHeight: 1.6,
        }}
      >
        {state.messages.map((m, i) => (
          <div key={i} style={{ marginBottom: "0.75rem" }}>
            <span
              style={{
                color: m.role === "user" ? "var(--color-primary)" : "var(--color-secondary)",
                fontWeight: 600,
              }}
            >
              {m.role === "user" ? "You" : "Claude"}
            </span>
            <br />
            {m.text || (m.role === "assistant" && state.sending ? "…" : "")}
          </div>
        ))}
        {state.error && (
          <div style={{ color: "var(--color-danger)", marginTop: "0.5rem" }}>
            Error: {state.error}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
        <textarea
          ref={inputRef}
          rows={3}
          style={{ flex: 1, margin: 0, resize: "vertical" }}
          placeholder="Ask Claude anything… (Enter to send, Shift+Enter for newline)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <button
          type="button"
          disabled={state.sending || !input.trim()}
          onClick={() => void handleSend()}
          style={{
            margin: 0,
            whiteSpace: "nowrap",
            padding: "0.5rem 1.25rem",
            background: "var(--color-primary)",
            color: "#000",
            border: 0,
            borderRadius: 4,
            fontWeight: 600,
          }}
        >
          Send
        </button>
      </div>
    </>
  );
}
