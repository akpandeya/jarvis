import { useCallback, useRef, useState } from "react";
import { streamChat, type ChatFrame } from "../lib/stream";

export interface ChatMsg {
  role: "user" | "assistant";
  text: string;
  placeholder?: string; // display text for user messages when origin is an auto-prompt
}

export interface ChatState {
  messages: ChatMsg[];
  sessionId: string | null;
  sending: boolean;
  error: string | null;
}

export function useChatStream(initial: Pick<ChatState, "messages" | "sessionId">) {
  const [state, setState] = useState<ChatState>({
    messages: initial.messages,
    sessionId: initial.sessionId,
    sending: false,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (
      message: string,
      opts: { model?: string; displayAs?: string } = {},
    ): Promise<void> => {
      if (!message.trim()) return;
      const displayUser: ChatMsg = {
        role: "user",
        text: opts.displayAs ?? message,
      };
      setState((s) => ({
        ...s,
        messages: [...s.messages, displayUser, { role: "assistant", text: "" }],
        sending: true,
        error: null,
      }));

      const ctl = new AbortController();
      abortRef.current = ctl;

      try {
        for await (const frame of streamChat(
          message,
          state.sessionId,
          opts.model ?? null,
        )) {
          applyFrame(frame, setState);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setState((s) => ({ ...s, sending: false, error: msg }));
        return;
      }
      setState((s) => ({ ...s, sending: false }));
    },
    [state.sessionId],
  );

  const resetSession = useCallback(() => {
    setState({ messages: [], sessionId: null, sending: false, error: null });
  }, []);

  return { state, send, resetSession };
}

function applyFrame(
  frame: ChatFrame,
  setState: React.Dispatch<React.SetStateAction<ChatState>>,
) {
  setState((s) => {
    const msgs = s.messages.slice();
    const last = msgs[msgs.length - 1];
    if (!last || last.role !== "assistant") return s;
    let sessionId = s.sessionId;
    if (frame.session_id && !sessionId) sessionId = frame.session_id;
    let error = s.error;
    if (frame.text) {
      msgs[msgs.length - 1] = { ...last, text: last.text + frame.text };
    }
    if (frame.error) {
      error = frame.error;
    }
    return { ...s, messages: msgs, sessionId, error };
  });
}
