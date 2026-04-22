import { useState } from "react";
import { Copy, Check, Table2 } from "lucide-react";
import type { SqlPayload } from "@/types";

interface Props {
  payload: SqlPayload;
}

export function SqlMessage({ payload }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(payload.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="max-w-[90%] w-full space-y-2" data-print-sql>
      {/* SQL block */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="flex items-center justify-between px-3 py-1.5 bg-muted/70 border-b border-border">
          <span className="text-xs font-mono text-muted-foreground">SQL</span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {copied ? (
              <Check className="w-3 h-3" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
          </button>
        </div>
        <pre className="px-3 py-2 text-xs font-mono overflow-x-auto bg-background">
          {payload.sql}
        </pre>
      </div>

      {/* Result table */}
      {payload.rows.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-muted/70 border-b border-border">
            <Table2 className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              {payload.rows.length} row{payload.rows.length !== 1 ? "s" : ""}
              {payload.truncated ? " (truncated)" : ""}
            </span>
          </div>
          <div className="overflow-x-auto max-h-64">
            <table className="text-xs w-full">
              <thead className="bg-muted/50 sticky top-0">
                <tr>
                  {payload.columns.map((col) => (
                    <th
                      key={col}
                      className="px-3 py-1.5 text-left font-medium text-muted-foreground border-b border-border"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {payload.rows.map((row, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                    {payload.columns.map((col) => (
                      <td key={col} className="px-3 py-1.5 font-mono">
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
