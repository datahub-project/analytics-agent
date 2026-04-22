import { useState } from "react";
import { Copy, Check } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TextPayload } from "@/types";

interface Props {
  payload: TextPayload;
  role: "user" | "assistant";
  isStreaming?: boolean;
}

function stripChartJson(text: string): string {
  return text.replace(/```(?:json)?\s*\{[^`]*"chart_schema"[^`]*\}[^`]*```/gs, "").trim();
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground hover:bg-muted/80"
      title="Copy to clipboard"
      data-print-hide
    >
      {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

export function TextMessage({ payload, role, isStreaming }: Props) {
  if (role === "user") {
    return (
      <div className="relative group rounded-lg px-4 py-3 text-sm bg-primary text-primary-foreground ml-auto max-w-[75%] whitespace-pre-wrap leading-relaxed" data-print-user>
        {payload.text}
        {isStreaming && <span className="inline-block w-1.5 h-4 bg-current ml-0.5 animate-pulse" />}
        <CopyButton text={payload.text} />
      </div>
    );
  }

  const cleanText = role === "assistant" ? stripChartJson(payload.text) : payload.text;

  return (
    <div className="relative group rounded-lg px-4 py-3 text-sm bg-muted text-foreground max-w-[90%] leading-relaxed prose prose-sm prose-neutral max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <pre className="bg-background border border-border rounded-md px-3 py-2 overflow-x-auto text-xs font-mono my-2">
                  <code className={className} {...props}>{children}</code>
                </pre>
              );
            }
            return (
              <code className="bg-background border border-border rounded px-1 py-0.5 text-xs font-mono" {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return <div className="overflow-x-auto my-2"><table className="text-xs border-collapse w-full">{children}</table></div>;
          },
          th({ children }) {
            return <th className="border border-border px-3 py-1.5 bg-muted/70 text-left font-medium">{children}</th>;
          },
          td({ children }) {
            return <td className="border border-border px-3 py-1.5">{children}</td>;
          },
          h1({ children }) { return <h1 className="text-base font-semibold mt-3 mb-1">{children}</h1>; },
          h2({ children }) { return <h2 className="text-sm font-semibold mt-3 mb-1">{children}</h2>; },
          h3({ children }) { return <h3 className="text-sm font-medium mt-2 mb-1">{children}</h3>; },
          ul({ children }) { return <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>; },
          ol({ children }) { return <ol className="list-decimal list-inside my-1 space-y-0.5">{children}</ol>; },
          li({ children }) { return <li className="ml-1">{children}</li>; },
          p({ children }) { return <p className="my-1">{children}</p>; },
          blockquote({ children }) {
            return (
              <blockquote className="border-l-2 border-border pl-3 italic text-muted-foreground my-2">
                {children}
              </blockquote>
            );
          },
          hr() { return <hr className="border-border my-3" />; },
          strong({ children }) { return <strong className="font-semibold">{children}</strong>; },
          em({ children }) { return <em className="italic">{children}</em>; },
        }}
      >
        {cleanText}
      </ReactMarkdown>
      {isStreaming && <span className="inline-block w-1.5 h-4 bg-current ml-0.5 animate-pulse" />}
      {!isStreaming && <CopyButton text={cleanText} />}
    </div>
  );
}
