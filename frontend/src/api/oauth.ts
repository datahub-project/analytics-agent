export interface OAuthAppConfig {
  client_id: string;
  client_secret?: string;
  redirect_uri?: string;
}

export async function saveOAuthAppConfig(engineName: string, config: OAuthAppConfig): Promise<void> {
  const res = await fetch(`/api/oauth/snowflake/${engineName}/app`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to save OAuth app config");
  }
}

export async function removeOAuthApp(engineName: string): Promise<void> {
  const res = await fetch(`/api/oauth/snowflake/${engineName}/app`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to remove OAuth app");
}

export async function saveSnowflakePat(
  engineName: string,
  token: string,
  username: string,
): Promise<void> {
  const res = await fetch(`/api/oauth/snowflake/${engineName}/pat`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, username }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to save PAT");
  }
}

export async function disconnectOAuth(engineName: string): Promise<void> {
  const res = await fetch(`/api/oauth/snowflake/${engineName}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to disconnect OAuth");
}

/**
 * Parse a Snowflake URL or account identifier into the account string
 * the connector expects (e.g. "fsbghmp-oub88836").
 *
 * Accepts:
 *   https://app.snowflake.com/fsbghmp/oub88836/
 *   https://fsbghmp-oub88836.snowflakecomputing.com
 *   fsbghmp-oub88836
 *   FSBGHMP-OUB88836
 */
export function parseSnowflakeAccount(input: string): string {
  const s = input.trim();
  // app.snowflake.com/<org>/<account>
  const appMatch = s.match(/app\.snowflake\.com\/([^/]+)\/([^/#?]+)/i);
  if (appMatch) return `${appMatch[1]}-${appMatch[2]}`.toLowerCase();
  // <account>.snowflakecomputing.com
  const computingMatch = s.match(/^https?:\/\/([^.]+)\.snowflakecomputing\.com/i);
  if (computingMatch) return computingMatch[1];
  // Already an account identifier — strip https:// if someone pasted the wrong thing
  return s.replace(/^https?:\/\//i, "").split(".")[0];
}

/** Local browser SSO — no client_id/secret needed. Blocks until auth completes. */
export async function browserSso(
  engineName: string,
  account?: string,
  user?: string,
): Promise<{ username: string }> {
  const res = await fetch(`/api/oauth/snowflake/${engineName}/browser-sso`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account: account ?? "", user: user ?? "" }),
    signal: AbortSignal.timeout(130_000),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Browser SSO failed");
  }
  return res.json();
}

export function initiateOAuthFlow(
  engineName: string,
  onSuccess: (username: string) => void,
  onError: (error: string) => void,
): void {
  const popup = window.open(
    `/api/oauth/snowflake/${engineName}/initiate`,
    "snowflake_oauth",
    "width=620,height=720,left=200,top=100"
  );

  const handler = (event: MessageEvent) => {
    if (event.data?.type === "snowflake_oauth_success") {
      window.removeEventListener("message", handler);
      popup?.close();
      onSuccess(event.data.username ?? "");
    } else if (event.data?.type === "snowflake_oauth_error") {
      window.removeEventListener("message", handler);
      popup?.close();
      onError(event.data.error ?? "OAuth failed");
    }
  };

  window.addEventListener("message", handler);

  // Cleanup if popup is closed manually
  const poll = setInterval(() => {
    if (popup?.closed) {
      clearInterval(poll);
      window.removeEventListener("message", handler);
    }
  }, 500);
}
