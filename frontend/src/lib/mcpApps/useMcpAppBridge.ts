/**
 * useMcpAppBridge — React hook that implements the host-side AppBridge.
 *
 * Attaches a window `message` listener scoped to the given iframe window.
 * Matches JSON-RPC 2.0 requests by method and id, then:
 *   1. Answers `ui/initialize` with `hostInfo` / `hostCapabilities` / `hostContext`.
 *   2. Waits for the app's `ui/notifications/initialized` handshake-complete
 *      signal, then pushes `ui/toolResult`. Pushing earlier drops the
 *      notification because the SDK only wires up its listener *after*
 *      validating the init response.
 *   3. Treats `ui/notifications/initialized` as the "app is live" signal for
 *      onReady() (the spec name; some older plans referenced `ui/ready`).
 *   4. Forwards `ui/notifications/size-changed` (app → host) to the caller so
 *      the wrapping iframe element can be resized to fit the app's content.
 *      Spec §"Notifications (View → Host)": params `{ height?, width? }` —
 *      only `height` is acted on; width is owned by the host layout.
 *   5. (Phase 2) Handles `tools/call` from the iframe: calls the scoped backend
 *      proxy endpoint and relays the CallToolResult back via postMessage.
 *   6. (Phase 2) Handles `ui/message` from the iframe: posts the text to
 *      POST /api/conversations/{id}/messages as a visible user turn and streams
 *      the agent response back through the normal SSE pipeline.
 */

import { useEffect, useRef } from "react";
import {
  PROTOCOL_VERSION,
  isJsonRpc,
  isRequest,
  isNotification,
  type JsonRpcRequest,
  type JsonRpcResponse,
  type JsonRpcError,
  type JsonRpcNotification,
  type UiInitializeResult,
  type UiToolInputNotification,
  type UiToolResultNotification,
  type CallToolResult,
  type McpContentBlock,
  type UiMessageContentBlock,
} from "./protocol";
import { callMcpAppTool } from "@/api/mcpApp";
import { streamMessage } from "@/api/stream";
import { generateTitle } from "@/api/conversations";
import { useConversationsStore } from "@/store/conversations";

export interface McpAppBridgeOptions {
  /** The iframe's contentWindow — set once the element mounts. */
  iframeWindow: Window | null;
  /** Tool input arguments (the kwargs the agent called the tool with). */
  toolInput: Record<string, unknown>;
  /**
   * Structured CallToolResult content. Either an array of content blocks
   * (preferred; matches MCP CallToolResult.content) or a string / object which
   * we wrap as a single text block for spec compliance.
   */
  toolResult: unknown;
  /** Called when the app sends ui/notifications/initialized (handshake done). */
  onReady?: () => void;
  /**
   * Called when the app publishes `ui/notifications/size-changed`.
   * Only invoked when `height` is a finite positive number; width is ignored.
   */
  onSizeChanged?: (height: number) => void;
  /**
   * Phase 2: conversation ID, needed to route `tools/call` to the correct
   * scoped proxy endpoint.  When absent, `tools/call` requests are rejected
   * with a JSON-RPC error instead of silently dropped.
   */
  conversationId?: string;
  /**
   * Phase 2: the app_id that identifies this specific MCP App instance.
   * Used as the path segment in `POST .../mcp-app/{app_id}/tool-call`.
   */
  appId?: string;
  /**
   * Phase 2: the message ID of the MCP_APP message that spawned this iframe.
   * Passed as `origin_message_id` when posting a `ui/message` so the backend
   * persists it in the payload and the frontend can anchor the SelectionChip
   * beneath the correct selector iframe on replay.
   */
  originMessageId?: string;
}

/**
 * Resolves once `isStreaming` is false. If the store is already idle it
 * resolves on the next microtask. Safe to call from any context because it
 * only reads/subscribes to the Zustand store.
 */
function waitForStreamingToEnd(): Promise<void> {
  if (!useConversationsStore.getState().isStreaming) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const unsub = useConversationsStore.subscribe((state) => {
      if (!state.isStreaming) {
        unsub();
        resolve();
      }
    });
  });
}

/** Coerce whatever we got into a spec-compliant CallToolResult. */
function toCallToolResult(raw: unknown): CallToolResult {
  if (Array.isArray(raw)) {
    return { content: raw as McpContentBlock[] };
  }
  if (raw && typeof raw === "object" && Array.isArray((raw as { content?: unknown }).content)) {
    return raw as CallToolResult;
  }
  const text = typeof raw === "string" ? raw : JSON.stringify(raw);
  return { content: [{ type: "text", text }] };
}

function reply<R>(
  target: Window,
  req: JsonRpcRequest,
  result: R
): void {
  const response: JsonRpcResponse<R> = {
    jsonrpc: "2.0",
    id: req.id,
    result,
  };
  target.postMessage(response, "*");
}

function push<P>(target: Window, notification: JsonRpcNotification<P>): void {
  target.postMessage(notification, "*");
}

function replyError(
  target: Window,
  req: JsonRpcRequest,
  code: number,
  message: string,
  data?: unknown
): void {
  const err: JsonRpcError = {
    jsonrpc: "2.0",
    id: req.id,
    error: { code, message, ...(data !== undefined ? { data } : {}) },
  };
  target.postMessage(err, "*");
}

export function useMcpAppBridge({
  iframeWindow,
  toolInput,
  toolResult,
  onReady,
  onSizeChanged,
  conversationId,
  appId,
  originMessageId,
}: McpAppBridgeOptions): void {
  // Keep stable refs so the effect doesn't re-run on every render
  const toolInputRef = useRef(toolInput);
  const toolResultRef = useRef(toolResult);
  const onReadyRef = useRef(onReady);
  const onSizeChangedRef = useRef(onSizeChanged);
  const conversationIdRef = useRef(conversationId);
  const appIdRef = useRef(appId);
  const originMessageIdRef = useRef(originMessageId);
  useEffect(() => {
    toolInputRef.current = toolInput;
  }, [toolInput]);
  useEffect(() => {
    toolResultRef.current = toolResult;
  }, [toolResult]);
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);
  useEffect(() => {
    onSizeChangedRef.current = onSizeChanged;
  }, [onSizeChanged]);
  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);
  useEffect(() => {
    appIdRef.current = appId;
  }, [appId]);
  useEffect(() => {
    originMessageIdRef.current = originMessageId;
  }, [originMessageId]);

  useEffect(() => {
    if (!iframeWindow) return;

    /**
     * Submit an iframe-authored selection through the flavor-C pipeline:
     * appends a SelectionChip locally, then streams the agent response
     * via the existing SSE endpoint tagged with source="mcp_app".
     *
     * `agentText` is what the agent sees in its conversation history — it
     * should be rich enough to prevent redundant follow-up tool calls (e.g.
     * re-running `get_context` for an already-disambiguated selection).
     * `displayText` is what the SelectionChip renders in the UI.
     *
     * Used by both `ui/message` and `ui/update-model-context` handlers.
     */
    function submitMcpAppTurn(
      agentText: string,
      displayText: string = agentText
    ): void {
      const convId = conversationIdRef.current;
      const aid = appIdRef.current;
      const oid = originMessageIdRef.current;
      if (!convId || !agentText) return;

      (async () => {
        await waitForStreamingToEnd();

        const store = useConversationsStore.getState();

        store.appendMessage({
          id: crypto.randomUUID(),
          event_type: "TEXT",
          role: "user",
          payload: {
            text: agentText,
            display_text: displayText,
            source: "mcp_app",
            ...(aid ? { app_id: aid } : {}),
            ...(oid ? { origin_message_id: oid } : {}),
          },
        });

        store.setStreaming(true);
        store.resetStreamingText();

        try {
          const stream = streamMessage(convId, agentText, undefined, {
            source: "mcp_app",
            display_text: displayText,
            ...(aid ? { app_id: aid } : {}),
            ...(oid ? { origin_message_id: oid } : {}),
          });
          let result = await stream.next();
          while (!result.done) {
            const event = result.value;
            const s = useConversationsStore.getState();
            if (event.event === "TEXT") {
              s.appendStreamingText(
                (event.payload as { text: string }).text
              );
            } else if (event.event === "TOOL_CALL") {
              s.markCurrentAsThinking();
              s.appendMessage({
                id: event.message_id,
                event_type: event.event,
                role: "assistant",
                payload: event.payload,
              });
            } else if (event.event !== "COMPLETE") {
              s.appendMessage({
                id: event.message_id,
                event_type: event.event,
                role: "assistant",
                payload: event.payload,
              });
            }
            result = await stream.next();
          }
        } catch (err) {
          useConversationsStore.getState().appendMessage({
            id: crypto.randomUUID(),
            event_type: "ERROR",
            role: "assistant",
            payload: { error: String(err) },
          });
        } finally {
          useConversationsStore.getState().setStreaming(false);
          generateTitle(convId)
            .then((r) => {
              if (r.updated) {
                useConversationsStore
                  .getState()
                  .updateConversationTitle(convId, r.title);
              }
            })
            .catch(() => {});
        }
      })();
    }

    function handleMessage(event: MessageEvent): void {
      // Only accept messages from our iframe
      if (event.source !== iframeWindow) return;

      const raw = event.data;
      if (!isJsonRpc(raw)) return;

      if (isRequest(raw)) {
        switch (raw.method) {
          case "ui/initialize": {
            // Ack with host-prefixed fields the MCP Apps SDK's Zod schema
            // requires. Advertise `tools` capability so the app knows it can
            // send `tools/call` requests.
            const result: UiInitializeResult = {
              protocolVersion: PROTOCOL_VERSION,
              hostInfo: {
                name: "analytics-agent",
                version: "0.1.0",
              },
              hostCapabilities: { tools: {}, message: {} },
              hostContext: {},
            };
            reply(iframeWindow!, raw, result);
            // NOTE: do NOT push ui/toolResult here — the app's toolResult
            // listener isn't wired up yet. We push it when the app signals
            // ui/notifications/initialized below (H6 fix).
            break;
          }

          case "tools/call": {
            // Phase 2: iframe requests a scoped MCP tool call.
            const convId = conversationIdRef.current;
            const aid = appIdRef.current;
            const params = (raw.params ?? {}) as {
              name?: string;
              arguments?: Record<string, unknown>;
            };
            const toolName = params.name ?? "";
            const args = params.arguments ?? {};

            if (!convId || !aid) {
              replyError(
                iframeWindow!,
                raw,
                -32603,
                "tools/call is not available: missing conversationId or appId"
              );
              break;
            }
            if (!toolName) {
              replyError(iframeWindow!, raw, -32602, "tools/call: missing tool name");
              break;
            }

            // Async: fire the REST call and relay the result back.
            callMcpAppTool(convId, aid, toolName, args)
              .then((result) => {
                const callToolResult: CallToolResult = {
                  content: result.content as McpContentBlock[],
                  isError: result.isError ?? false,
                };
                reply(iframeWindow!, raw, callToolResult);
              })
              .catch((err: unknown) => {
                replyError(
                  iframeWindow!,
                  raw,
                  -32603,
                  err instanceof Error ? err.message : String(err)
                );
              });
            break;
          }

          case "ui/message": {
            // Phase 2: iframe authors a user turn on behalf of the user.
            // Per spec §"ui/message": params.content is a content block object
            // { type: "text", text: string }, NOT a plain string.
            const msgParams = (raw.params ?? {}) as {
              role?: string;
              content?: UiMessageContentBlock | string;
            };
            const rawContent = msgParams.content;
            const content = (
              typeof rawContent === "string"
                ? rawContent
                : (rawContent as UiMessageContentBlock | undefined)?.text ?? ""
            ).trim();

            if (!conversationIdRef.current || !content) {
              replyError(
                iframeWindow!,
                raw,
                -32602,
                "ui/message: missing conversationId or content"
              );
              break;
            }

            // Acknowledge immediately so the iframe's "sending" state resolves.
            reply(iframeWindow!, raw, {});
            submitMcpAppTurn(content);
            break;
          }

          case "ui/update-model-context": {
            // Per MCP Apps spec §"ui/update-model-context":
            //   params: { content?: ContentBlock[], structuredContent?: object }
            // Spec allows the host to "MAY defer sending the context to the
            // model until the next user message" OR process immediately.
            // Apps that use this for selection flows (like the card selector)
            // expect immediate processing — the iframe shows "Sending…" on
            // click and waits for a new agent turn.
            //
            // We extract a human-readable label for the SelectionChip, prefer
            // `structuredContent.selected_name`, then fall back to the content
            // blocks' text, then a JSON blob.
            const ctxParams = (raw.params ?? {}) as {
              content?: Array<{ type: string; text?: string }>;
              structuredContent?: Record<string, unknown>;
            };

            const structured = ctxParams.structuredContent;

            // Display label: short, human-readable string for the SelectionChip.
            let displayText = "";
            if (structured) {
              const named =
                (structured as { selected_name?: unknown }).selected_name ??
                (structured as { name?: unknown }).name ??
                (structured as { label?: unknown }).label;
              if (typeof named === "string" && named.trim()) {
                displayText = named.trim();
              }
            }
            if (!displayText && Array.isArray(ctxParams.content)) {
              const texts = ctxParams.content
                .filter((b) => b && b.type === "text" && typeof b.text === "string")
                .map((b) => b.text as string);
              if (texts.length > 0) displayText = texts.join(" ").trim();
            }

            // Agent-facing text: richer than the display label so the LLM
            // doesn't re-disambiguate an already-resolved selection (e.g. by
            // re-calling `get_context` when it already has the URN). Includes
            // identifier(s) from structuredContent + an explicit instruction.
            let agentText = displayText;
            if (structured) {
              const urn =
                (structured as { selected_urn?: unknown }).selected_urn ??
                (structured as { urn?: unknown }).urn ??
                (structured as { id?: unknown }).id;
              const custom =
                (structured as { custom_response?: unknown }).custom_response;
              const parts: string[] = [];
              if (displayText) {
                parts.push(
                  `The user selected "${displayText}" from the previous interactive card.`
                );
              }
              if (typeof urn === "string" && urn.trim()) {
                parts.push(`Identifier: ${urn.trim()}.`);
              }
              if (typeof custom === "string" && custom.trim()) {
                parts.push(`Additional input: ${custom.trim()}.`);
              }
              if (parts.length > 0) {
                parts.push(
                  "This selection is already disambiguated — do NOT call `get_context` or other disambiguation tools for this concept; use it directly and continue with the original request."
                );
                agentText = parts.join(" ");
              }
            }
            if (!agentText && structured) {
              try {
                agentText = JSON.stringify(structured);
                if (!displayText) displayText = agentText;
              } catch {
                agentText = "";
              }
            }

            // Always ack — spec requires a response with empty result on success.
            reply(iframeWindow!, raw, {});

            if (agentText) {
              submitMcpAppTurn(agentText, displayText || agentText);
            }
            break;
          }

          case "sendOpenLink":
            // Phase 3 — not yet wired
            console.warn(
              `[MCPAppBridge] method "sendOpenLink" received but not yet handled.`
            );
            break;

          default:
            break;
        }
      } else if (isNotification(raw)) {
        switch (raw.method) {
          case "ui/notifications/initialized":
          case "ui/ready": {
            // Spec §"Notifications (Host → View)":
            //   1. MUST send ui/notifications/tool-input with the tool arguments
            //   2. MUST follow with ui/notifications/tool-result containing the
            //      full CallToolResult (with structured content blocks).
            // The View ignores tool-result if tool-input hasn't arrived yet.
            const toolInputPush: UiToolInputNotification = {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-input",
              params: { arguments: toolInputRef.current },
            };
            const callToolResult = toCallToolResult(toolResultRef.current);
            const toolResultPush: UiToolResultNotification = {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: callToolResult,
            };
            push(iframeWindow!, toolInputPush);
            push(iframeWindow!, toolResultPush);
            onReadyRef.current?.();
            break;
          }
          case "ui/notifications/size-changed": {
            // Spec: params { height?: number, width?: number }. We only
            // act on height — width is fixed by the chat-column layout.
            const params = (raw.params ?? {}) as {
              height?: unknown;
              width?: unknown;
            };
            const h =
              typeof params.height === "number" && Number.isFinite(params.height)
                ? params.height
                : null;
            if (h !== null && h > 0) {
              onSizeChangedRef.current?.(h);
            }
            break;
          }
          case "ui/context/update":
            // Phase 2 — not yet wired
            console.warn("[MCPAppBridge] ui/context/update not yet handled.");
            break;
          default:
            break;
        }
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [iframeWindow]);
}
