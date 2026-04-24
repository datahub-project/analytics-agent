/**
 * MCPAppMessage — adapter between an MCP_APP SSE payload and MCPAppFrame.
 *
 * On mount, always fetches HTML via GET .../mcp-app/{message_id}/ui.
 * The prefetched disk cache on the backend makes this fast for first render;
 * the same code path handles replay when the conversation is reloaded.
 *
 * Shows a skeleton while the fetch is in flight, a graceful placeholder on
 * 404 (both cache and server unavailable), and the sandboxed iframe once ready.
 */

import { useEffect, useState } from "react";
import { Loader2, AppWindow } from "lucide-react";
import type { MCPAppPayload } from "@/types";
import { fetchMcpAppUi } from "@/api/mcpApp";
import { MCPAppFrame } from "@/lib/mcpApps/MCPAppFrame";

interface Props {
  messageId: string;
  conversationId: string;
  payload: MCPAppPayload;
}

type FetchState =
  | { status: "loading" }
  | { status: "ready"; html: string; csp: string | null; permissions: string[] }
  | { status: "unavailable" }
  | { status: "error"; message: string };

export function MCPAppMessage({ messageId, conversationId, payload }: Props) {
  const [fetchState, setFetchState] = useState<FetchState>({ status: "loading" });
  const [appReady, setAppReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFetchState({ status: "loading" });
    setAppReady(false);

    fetchMcpAppUi(conversationId, messageId)
      .then((ui) => {
        if (cancelled) return;
        if (ui === null) {
          setFetchState({ status: "unavailable" });
        } else {
          setFetchState({
            status: "ready",
            html: ui.html,
            csp: ui.csp,
            permissions: ui.permissions,
          });
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFetchState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId, messageId]);

  return (
    <div className="w-full rounded-lg border border-border overflow-hidden bg-background">
      {/* Header strip */}
      <div className="flex items-center gap-2 px-3 py-2 bg-muted/40 border-b border-border text-xs text-muted-foreground">
        <AppWindow className="w-3.5 h-3.5 shrink-0" />
        <span className="font-mono truncate">{payload.tool_name}</span>
        {payload.server_name && (
          <span className="ml-auto shrink-0 opacity-60">{payload.server_name}</span>
        )}
      </div>

      {/* Content area */}
      {fetchState.status === "loading" && (
        <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading app…
        </div>
      )}

      {fetchState.status === "unavailable" && (
        <div className="px-4 py-6 text-sm text-muted-foreground text-center">
          <p className="font-medium">App unavailable</p>
          <p className="mt-1 text-xs opacity-70">
            The MCP server is offline and no cached version is available.
          </p>
        </div>
      )}

      {fetchState.status === "error" && (
        <div className="px-4 py-4 text-xs text-red-500 bg-red-50 border-t border-red-100 font-mono">
          {fetchState.message}
        </div>
      )}

      {fetchState.status === "ready" && (
        <div className="relative">
          {!appReady && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-10">
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
            </div>
          )}
          <MCPAppFrame
            html={fetchState.html}
            toolInput={payload.tool_input}
            toolResult={payload.tool_result}
            csp={fetchState.csp}
            permissions={fetchState.permissions}
            onReady={() => setAppReady(true)}
            className="w-full border-0 block"
            conversationId={conversationId}
            appId={payload.app_id}
            originMessageId={messageId}
          />
        </div>
      )}
    </div>
  );
}
