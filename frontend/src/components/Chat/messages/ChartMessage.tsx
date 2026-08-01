import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import vegaEmbed from "vega-embed";
import type { ChartPayload } from "@/types";

interface Props {
  payload: ChartPayload;
  onRenderError?: (error: string) => void;
}

/** Minimal slice of the Vega view API this component uses. */
interface VegaView {
  finalize: () => void;
  toImageURL: (type: string, scale?: number) => Promise<string>;
}

export function ChartMessage({ payload, onRenderError }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Holds the live Vega view so it can be disposed on unmount. Without this the
  // view keeps its RAF loop and listeners alive; once the message list is
  // virtualized and unmounts off-screen charts, leaking them defeats the point.
  const viewRef = useRef<VegaView | null>(null);
  const [embedError, setEmbedError] = useState<string | null>(null);
  // Gate the download button on a rendered view (viewRef is a ref, not reactive).
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || !payload.vega_lite_spec) return;
    setEmbedError(null);
    setReady(false);

    const container = containerRef.current;

    const embed = (width: number) => {
      const spec = {
        ...payload.vega_lite_spec,
        width: Math.max(width - 40, 200),
        autosize: { type: "fit-x", contains: "padding" },
      } as never;

      vegaEmbed(container, spec, {
        mode: "vega-lite",
        renderer: "svg",
        actions: { export: true, editor: false, source: false },
        tooltip: { theme: "custom" },
      })
        .then((result) => {
          viewRef.current = result.view;
          setReady(true);
        })
        .catch((err) => {
          console.error("Vega-Lite render error:", err);
          const msg = String(err?.message || err);
          setEmbedError(msg);
          onRenderError?.(msg);
        });
    };

    // Use ResizeObserver so chart fills width even after layout settles
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 50) {
        embed(w);
        observer.disconnect(); // embed once at stable width
      }
    });
    observer.observe(container);

    // Fallback if already sized
    if (container.clientWidth > 50) {
      embed(container.clientWidth);
      observer.disconnect();
    }

    return () => {
      observer.disconnect();
      viewRef.current?.finalize();
      viewRef.current = null;
    };
  }, [payload.vega_lite_spec]);

  const handleDownloadPng = async () => {
    const view = viewRef.current;
    if (!view) return;
    try {
      // 2× scale for a crisp export regardless of on-screen size.
      const url = await view.toImageURL("png", 2);
      const a = document.createElement("a");
      a.href = url;
      a.download = "chart.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      console.error("Chart PNG export failed:", err);
    }
  };

  if (!payload.vega_lite_spec || Object.keys(payload.vega_lite_spec).length === 0) {
    return null;
  }

  return (
    <div className="w-full rounded-lg border border-border overflow-hidden bg-background p-4">
      {embedError ? (
        <div className="text-xs text-red-500 bg-red-50 border border-red-200 rounded p-3 font-mono">
          Chart render error: {embedError}
        </div>
      ) : (
        <>
          {ready && (
            <div className="flex justify-end mb-1">
              <button
                onClick={handleDownloadPng}
                title="Download chart as PNG"
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground
                           px-2 py-1 rounded hover:bg-muted/60 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                PNG
              </button>
            </div>
          )}
          <div ref={containerRef} className="w-full" />
        </>
      )}
      {payload.reasoning && (
        <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
          {payload.reasoning}
        </p>
      )}
    </div>
  );
}
