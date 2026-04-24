/**
 * MCPAppFrame — sandboxed iframe wrapper for MCP App HTML.
 *
 * Security posture:
 *   - sandbox="allow-scripts"  (no allow-same-origin, no allow-forms, etc.)
 *   - csp attribute on the iframe element (W3C, Chromium-enforced before any
 *     script runs; stronger than meta CSP because it supports frame-ancestors).
 *   - When csp is provided and the browser doesn't support the iframe csp
 *     attribute (non-Chromium), we inject a <meta http-equiv=CSP> into
 *     the HTML before setting srcDoc as a documented weaker fallback.
 *
 * Wires up useMcpAppBridge so the app receives ui/initialize ack +
 * ui/toolResult push as soon as it loads.
 *
 * Height: starts at MIN_FRAME_HEIGHT_PX and grows via
 * `ui/notifications/size-changed` from the app. We never shrink below
 * the min, and we ignore non-finite or non-positive values from the
 * app (defensive — a buggy app shouldn't collapse the frame to 0).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMcpAppBridge } from "./useMcpAppBridge";

const MIN_FRAME_HEIGHT_PX = 120;

export interface MCPAppFrameProps {
  /** Raw HTML to render inside the iframe. */
  html: string;
  /** Tool input arguments (what the agent called the tool with). */
  toolInput: Record<string, unknown>;
  /** Tool result to push to the app after ui/initialize. */
  toolResult: unknown;
  /** CSP string from the MCP server's _meta.ui.csp field. */
  csp?: string | null;
  /** permissions from the MCP server's _meta.ui.permissions field. */
  permissions?: string[];
  /** Called when the app sends ui/notifications/initialized. */
  onReady?: () => void;
  className?: string;
  /**
   * Phase 2: conversation the frame lives in. Passed to useMcpAppBridge so
   * tools/call requests can be routed to the correct backend endpoint.
   */
  conversationId?: string;
  /**
   * Phase 2: the app_id for this MCP App instance — used as the path segment
   * in POST .../mcp-app/{app_id}/tool-call.
   */
  appId?: string;
  /**
   * Phase 2: the message ID of the MCP_APP message that created this frame.
   * Forwarded to useMcpAppBridge so `ui/message` posts include it as
   * `origin_message_id`, enabling the SelectionChip to be anchored under this
   * selector on replay.
   */
  originMessageId?: string;
}

/** Returns true if the browser supports the iframe `csp` attribute. */
function supportsCspAttribute(): boolean {
  return "csp" in HTMLIFrameElement.prototype;
}

/** Inject a <meta http-equiv=CSP> as a documented weaker fallback. */
function injectMetaCsp(html: string, csp: string): string {
  const metaTag = `<meta http-equiv="Content-Security-Policy" content="${csp.replace(/"/g, "&quot;")}">`;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/(<head[^>]*>)/i, `$1\n  ${metaTag}`);
  }
  // No <head> — prepend before everything
  return `${metaTag}\n${html}`;
}

export function MCPAppFrame({
  html,
  toolInput,
  toolResult,
  csp,
  onReady,
  className,
  conversationId,
  appId,
  originMessageId,
}: MCPAppFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [iframeWindow, setIframeWindow] = useState<Window | null>(null);
  const [frameHeight, setFrameHeight] = useState<number>(MIN_FRAME_HEIGHT_PX);

  // Resolve srcDoc: inject meta CSP fallback for non-Chromium if needed
  const srcDoc = (() => {
    if (csp && !supportsCspAttribute()) {
      return injectMetaCsp(html, csp);
    }
    return html;
  })();

  const handleSizeChanged = useCallback((height: number) => {
    setFrameHeight(Math.max(MIN_FRAME_HEIGHT_PX, Math.ceil(height)));
  }, []);

  useMcpAppBridge({
    iframeWindow,
    toolInput,
    toolResult,
    onReady,
    onSizeChanged: handleSizeChanged,
    conversationId,
    appId,
    originMessageId,
  });

  const handleLoad = useCallback(() => {
    setIframeWindow(iframeRef.current?.contentWindow ?? null);
  }, []);

  useEffect(() => {
    setIframeWindow(null);
    setFrameHeight(MIN_FRAME_HEIGHT_PX);
  }, [srcDoc]);

  return (
    <iframe
      ref={iframeRef}
      title="MCP App"
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      // csp attribute: Chromium enforces this before any script runs.
      // TypeScript's lib.dom.d.ts doesn't include this attribute yet, so we
      // spread it as a plain object to avoid a type error.
      {...(csp ? { csp } : {})}
      onLoad={handleLoad}
      className={className}
      style={{ height: `${frameHeight}px` }}
      referrerPolicy="no-referrer"
    />
  );
}
