import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw, Tag, ArrowUpCircle, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getVersionInfo, getReleases, type VersionInfo, type Release } from "@/api/settings";

const GITHUB_RELEASES_URL =
  "https://github.com/datahub-project/analytics-agent/releases";

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function AboutSection() {
  const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null);
  const [releases, setReleases] = useState<Release[]>([]);
  const [loadingVersion, setLoadingVersion] = useState(true);
  const [loadingReleases, setLoadingReleases] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setLoadingVersion(true);
    setLoadingReleases(true);
    const [v, r] = await Promise.all([getVersionInfo(), getReleases()]);
    setVersionInfo(v);
    setReleases(r);
    setLoadingVersion(false);
    setLoadingReleases(false);
  };

  useEffect(() => {
    load();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <div className="space-y-6">
      {/* Version card */}
      <div className="border border-border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Version</h3>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
            title="Check for updates"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>

        {loadingVersion ? (
          <div className="text-xs text-muted-foreground animate-pulse">Checking version…</div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground w-28 flex-shrink-0">Installed</span>
              <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-xs">
                {versionInfo?.current_version ?? "unknown"}
              </code>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground w-28 flex-shrink-0">Latest release</span>
              {versionInfo?.latest_version ? (
                <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-xs">
                  {versionInfo.latest_version}
                </code>
              ) : (
                <span className="text-muted-foreground text-xs italic">unavailable</span>
              )}
            </div>

            {versionInfo?.update_available && (
              <div className="space-y-2 pt-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                    <ArrowUpCircle className="w-3.5 h-3.5 flex-shrink-0" />
                    A newer version is available
                  </span>
                  <a
                    href={GITHUB_RELEASES_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs border border-amber-500/40
                               text-amber-600 dark:text-amber-400 rounded-md px-3 py-1.5
                               hover:bg-amber-500/10 transition-colors flex-shrink-0"
                  >
                    <ArrowUpCircle className="w-3 h-3" />
                    Release notes
                  </a>
                </div>
                <div className="bg-muted rounded px-3 py-2 font-mono text-xs text-muted-foreground select-all">
                  analytics-agent upgrade
                </div>
              </div>
            )}

            {versionInfo && !versionInfo.update_available && versionInfo.latest_version && (
              <div className="flex items-center gap-1.5 pt-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                <span className="text-xs text-emerald-600 dark:text-emerald-400">
                  You&apos;re up to date
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Changelog */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Changelog</h3>
          <a
            href={GITHUB_RELEASES_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            All releases
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        {loadingReleases ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="border border-border rounded-lg p-4 animate-pulse space-y-2">
                <div className="h-3 bg-muted rounded w-24" />
                <div className="h-2 bg-muted rounded w-48" />
              </div>
            ))}
          </div>
        ) : releases.length === 0 ? (
          <div className="text-xs text-muted-foreground italic">
            Could not load release notes. Check your network connection or{" "}
            <a
              href={GITHUB_RELEASES_URL}
              target="_blank"
              rel="noreferrer"
              className="underline hover:no-underline"
            >
              view on GitHub
            </a>
            .
          </div>
        ) : (
          <div className="space-y-3">
            {releases.map((release) => (
              <ReleaseCard
                key={release.tag_name}
                release={release}
                isInstalled={
                  !!versionInfo &&
                  release.tag_name.replace(/^v/, "") === versionInfo.current_version
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ReleaseCard({
  release,
  isInstalled,
}: {
  release: Release;
  isInstalled: boolean;
}) {
  const [expanded, setExpanded] = useState(isInstalled);
  const hasBody = Boolean(release.body);

  return (
    <div
      className={`border rounded-lg overflow-hidden ${
        isInstalled ? "border-primary/60 bg-primary/10" : "border-border"
      }`}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/40 transition-colors text-left gap-2"
      >
        <div className="flex items-center gap-2 min-w-0">
          <Tag className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
          <span className="text-sm font-medium font-mono truncate">{release.name}</span>
          {isInstalled && (
            <span className="text-xs bg-primary/15 text-primary px-1.5 py-0.5 rounded font-medium flex-shrink-0">
              installed
            </span>
          )}
          {release.prerelease && (
            <span className="text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded font-medium flex-shrink-0">
              pre-release
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-muted-foreground">{formatDate(release.published_at)}</span>
          <a
            href={release.html_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="View on GitHub"
          >
            <ExternalLink className="w-3 h-3" />
          </a>
          <ChevronDown
            className={`w-3.5 h-3.5 text-muted-foreground transition-transform duration-200 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {/* CSS grid-rows transition — animates open/close without JS height measurement */}
      <div
        className="grid transition-[grid-template-rows] duration-200"
        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border/60 px-4 pb-4 pt-3">
            {hasBody ? (
              <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed
                              [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs [&_h4]:text-xs
                              [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold
                              [&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2
                              [&_ul]:pl-4 [&_ol]:pl-4 [&_li]:my-0.5
                              [&_a]:text-primary [&_a]:no-underline [&_a:hover]:underline
                              [&_code]:bg-muted [&_code]:px-1 [&_code]:rounded [&_code]:text-xs [&_code]:font-mono
                              [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-x-auto">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{release.body}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">No release notes provided.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
