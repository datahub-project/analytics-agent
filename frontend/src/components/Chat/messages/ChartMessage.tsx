import { useEffect, useRef, useState } from "react";
import vegaEmbed from "vega-embed";
import type { ChartPayload } from "@/types";

interface Props {
  payload: ChartPayload;
  onRenderError?: (error: string) => void;
}

export function ChartMessage({ payload, onRenderError }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [embedError, setEmbedError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || !payload.vega_lite_spec) return;
    setEmbedError(null);

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
      }).catch((err) => {
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

    return () => observer.disconnect();
  }, [payload.vega_lite_spec]);

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
        <div ref={containerRef} className="w-full" />
      )}
      {payload.reasoning && (
        <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
          {payload.reasoning}
        </p>
      )}
    </div>
  );
}
