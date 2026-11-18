type SseEvent = [string, any];

/** Incremental SSE decoding; never buffers the full HTTP response. */
export async function* parseEventStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let line = "";
  let skipLF = false;
  let event: string | null = null;
  let data: string[] = [];

  function dispatch(): SseEvent | undefined {
    const result: SseEvent | undefined = event !== null || data.length
      ? [event || "message", data.join("\n") ? JSON.parse(data.join("\n")) : null]
      : undefined;
    event = null;
    data = [];
    return result;
  }

  function consumeLine(value: string): SseEvent | undefined {
    if (value === "") return dispatch();
    if (value.startsWith(":")) return;
    const colon = value.indexOf(":");
    const field = colon < 0 ? value : value.slice(0, colon);
    let content = colon < 0 ? "" : value.slice(colon + 1);
    if (content.startsWith(" ")) content = content.slice(1);
    if (field === "event") event = content;
    if (field === "data") data.push(content);
  }

  function* consumeText(text: string): Generator<SseEvent> {
    for (const char of text) {
      if (skipLF) {
        skipLF = false;
        if (char === "\n") continue;
      }
      if (char === "\r" || char === "\n") {
        const result = consumeLine(line);
        line = "";
        skipLF = char === "\r";
        if (result) yield result;
      } else {
        line += char;
      }
    }
  }

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      yield* consumeText(decoder.decode(chunk.value, { stream: true }));
    }
    yield* consumeText(decoder.decode());
    if (line) consumeLine(line);
    // Compatibility with upstreams that omit the final blank separator.
    const result = dispatch();
    if (result) yield result;
  } finally {
    try {
      await reader.cancel();
    } catch {
      // Preserve the original network/JSON error if cancellation also fails.
    }
    reader.releaseLock();
  }
}
