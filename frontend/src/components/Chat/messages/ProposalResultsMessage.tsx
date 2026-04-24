/**
 * ProposalResultsMessage — renders the outcomes of a /improve-context write
 * run as a compact status card. Each row shows a green check (success) or
 * red X (error), the kind badge, the title, the written URN, and an
 * "Open in DataHub" link for successes.
 */

import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, FilePlus, FileText, Tag, ExternalLink, ClipboardList } from "lucide-react";
import type { ProposalResultItem, ProposalResultsPayload } from "@/types";
import { listConnections } from "@/api/settings";

interface Props {
  payload: ProposalResultsPayload;
}

const KIND_META: Record<
  ProposalResultItem["kind"],
  { label: string; className: string; icon: React.ReactNode }
> = {
  new_doc: {
    label: "New doc",
    className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
    icon: <FilePlus className="w-3 h-3" />,
  },
  update_doc: {
    label: "Update doc",
    className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
    icon: <FileText className="w-3 h-3" />,
  },
  fix_description: {
    label: "Fix description",
    className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
    icon: <Tag className="w-3 h-3" />,
  },
};

/** Derive the DataHub UI base URL from the GMS URL stored in the connection config.
 *  e.g. "https://instance.acryl.io/gms" → "https://instance.acryl.io" */
function useDataHubBaseUrl(): string | null {
  const [baseUrl, setBaseUrl] = useState<string | null>(null);

  useEffect(() => {
    listConnections()
      .then((connections) => {
        const dhConn = connections.find(
          (c) => c.type === "datahub" || c.type === "datahub_mcp"
        );
        if (!dhConn) return;
        const urlField = dhConn.fields.find((f) => f.key === "url");
        if (!urlField?.value) return;
        // Strip trailing /gms to get the UI base
        const raw = urlField.value.replace(/\/gms\/?$/, "").replace(/\/$/, "");
        setBaseUrl(raw);
      })
      .catch(() => {});
  }, []);

  return baseUrl;
}

function buildEntityUrl(baseUrl: string, urn: string): string {
  return `${baseUrl}/entity/${encodeURIComponent(urn)}`;
}

export function ProposalResultsMessage({ payload }: Props) {
  const { results } = payload;
  const baseUrl = useDataHubBaseUrl();

  const successCount = results.filter((r) => r.status === "success").length;
  const total = results.length;

  return (
    <div className="w-full rounded-lg border border-border overflow-hidden bg-background">
      {/* Header strip */}
      <div className="flex items-center gap-2 px-3 py-2 bg-muted/40 border-b border-border text-xs text-muted-foreground">
        <ClipboardList className="w-3.5 h-3.5 shrink-0" />
        <span className="font-medium">Write results</span>
        <span className="ml-auto shrink-0 opacity-60">
          {successCount} of {total} succeeded
        </span>
      </div>

      {/* Results list */}
      <ul className="divide-y divide-border">
        {results.map((item) => {
          const meta = KIND_META[item.kind];
          const isSuccess = item.status === "success";

          return (
            <li key={item.id} className="flex gap-3 px-4 py-3">
              {/* Status icon */}
              <div className="mt-0.5 shrink-0">
                {isSuccess ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-500" />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  {/* Kind badge */}
                  <span
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${meta.className}`}
                  >
                    {meta.icon}
                    {meta.label}
                  </span>
                  <span className="text-sm font-medium text-foreground truncate">
                    {item.title}
                  </span>
                </div>

                {isSuccess && item.urn && (
                  <div className="flex items-center gap-2 mt-1">
                    <code className="text-[10px] font-mono text-muted-foreground/70 truncate">
                      {item.urn}
                    </code>
                    {baseUrl && (
                      <a
                        href={buildEntityUrl(baseUrl, item.urn)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-[10px] text-primary hover:underline shrink-0"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="w-2.5 h-2.5" />
                        Open
                      </a>
                    )}
                  </div>
                )}

                {!isSuccess && item.error && (
                  <p className="mt-1 text-[10px] font-mono text-red-500/90 break-words">
                    {item.error}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {/* Footer summary */}
      <div className="px-4 py-2.5 border-t border-border bg-muted/20 text-xs text-muted-foreground">
        {successCount === total
          ? `All ${total} change${total !== 1 ? "s" : ""} applied successfully.`
          : successCount === 0
          ? `All ${total} change${total !== 1 ? "s" : ""} failed.`
          : `${successCount} of ${total} changes applied; ${total - successCount} failed.`}
      </div>
    </div>
  );
}
