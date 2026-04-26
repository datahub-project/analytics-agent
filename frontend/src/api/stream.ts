import type { SSEEvent } from "@/types";

export async function* reattachStream(
  conversationId: string,
  signal?: AbortSignal
): AsyncIterator<SSEEvent> {
  const res = await fetch(`/api/conversations/${conversationId}/stream`, { signal });
  if (!res.ok || res.status === 204 || !res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() ?? "";
    for (const chunk of lines) {
      const dataLine = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      try {
        const event: SSEEvent = JSON.parse(dataLine.slice(6));
        yield event;
      } catch {
        // malformed chunk, skip
      }
    }
  }
}

export async function* streamMessage(
  conversationId: string,
  text: string,
  signal?: AbortSignal
): AsyncIterator<SSEEvent> {
  const res = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() ?? "";

    for (const chunk of lines) {
      const dataLine = chunk
        .split("\n")
        .find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      try {
        const event: SSEEvent = JSON.parse(dataLine.slice(6));
        yield event;
      } catch {
        // malformed chunk, skip
      }
    }
  }
}
