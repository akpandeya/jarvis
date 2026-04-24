// Consumes the existing /api/chat/stream NDJSON-over-SSE endpoint.
// Yields the parsed frames one by one.

export interface ChatFrame {
  session_id?: string;
  text?: string;
  error?: string;
  done?: boolean;
}

export async function* streamChat(
  message: string,
  sessionId: string | null,
  model: string | null,
): AsyncGenerator<ChatFrame> {
  const fd = new FormData();
  fd.append("message", message);
  if (sessionId) fd.append("session_id", sessionId);
  if (model) fd.append("model", model);

  const resp = await fetch("/api/chat/stream", { method: "POST", body: fd });
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    yield { error: `HTTP ${resp.status}: ${text || "no body"}` };
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const frame = JSON.parse(line.slice(6)) as ChatFrame;
        yield frame;
      } catch {
        // Skip malformed frames.
      }
    }
  }
}
