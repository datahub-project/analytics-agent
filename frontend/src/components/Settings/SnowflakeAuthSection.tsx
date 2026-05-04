/**
 * SnowflakeAuthSection
 *
 * A self-contained auth-method picker + credential form for Snowflake connections.
 * Designed to live inside a ~600px expanded connection card in the settings panel.
 *
 * Auth methods (mutually exclusive):
 *   password   — username + password
 *   privatekey — username + PEM key
 *   sso        — username/email → opens system browser (externalbrowser)
 *   pat        — single Programmatic Access Token
 *   oauth      — client_id + client_secret (deployed server scenario)
 */

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Lock,
  Key,
  LogIn,
  Fingerprint,
  Shield,
  Eye,
  EyeOff,
  Loader2,
  AlertCircle,
  LogOut,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AuthMethod = "password" | "privatekey" | "sso" | "pat" | "oauth";

interface Props {
  /** Currently active auth — null when not yet connected. */
  connectedAuth: { method: AuthMethod; username: string } | null;
  onConnect: (method: string, fields: Record<string, string>) => Promise<void>;
  onDisconnect: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

interface MethodMeta {
  id: AuthMethod;
  label: string;
  shortLabel: string;
  icon: React.ReactNode;
  description: string;
  hint?: string;
}

const METHODS: MethodMeta[] = [
  {
    id: "password",
    label: "Password",
    shortLabel: "Password",
    icon: <Lock className="w-3 h-3" />,
    description: "Username and password — suitable for service accounts.",
  },
  {
    id: "privatekey",
    label: "Private Key",
    shortLabel: "Key",
    icon: <Key className="w-3 h-3" />,
    description: "Username with a PEM private key — recommended for automation.",
  },
  {
    id: "sso",
    label: "SSO",
    shortLabel: "SSO",
    icon: <LogIn className="w-3 h-3" />,
    description: "Opens your browser for Okta, Azure AD, or another IdP.",
    hint: "A browser window will open to complete sign-in.",
  },
  {
    id: "pat",
    label: "PAT",
    shortLabel: "PAT",
    icon: <Fingerprint className="w-3 h-3" />,
    description: "Paste a Programmatic Access Token.",
  },
  {
    id: "oauth",
    label: "OAuth App",
    shortLabel: "OAuth",
    icon: <Shield className="w-3 h-3" />,
    description: "Client credentials for a deployed server OAuth app.",
  },
];

// ---------------------------------------------------------------------------
// Small atoms
// ---------------------------------------------------------------------------

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium text-muted-foreground mb-1">
      {children}
    </label>
  );
}

function Input({
  type = "text",
  value,
  onChange,
  placeholder,
  autoFocus,
  onKeyDown,
}: {
  type?: "text" | "password";
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === "password";

  return (
    <div className="relative">
      <input
        type={isPassword && !revealed ? "password" : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onKeyDown={onKeyDown}
        className="w-full text-xs bg-background border border-border rounded-md px-2.5 py-1.5
                   focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/40
                   placeholder:text-muted-foreground/40 font-mono transition-colors"
      />
      {isPassword && (
        <button
          type="button"
          tabIndex={-1}
          onClick={() => setRevealed((v) => !v)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
        >
          {revealed ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
        </button>
      )}
    </div>
  );
}

function Textarea({
  value,
  onChange,
  placeholder,
  rows = 6,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      spellCheck={false}
      className="w-full text-xs bg-background border border-border rounded-md px-2.5 py-2
                 focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/40
                 placeholder:text-muted-foreground/40 font-mono resize-y leading-relaxed transition-colors"
    />
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs px-3 py-2 rounded-md border bg-red-50 border-red-200 text-red-700 dark:bg-red-950/30 dark:border-red-900/50 dark:text-red-400">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connected state banner — shown at the top when auth is active
// ---------------------------------------------------------------------------

function ConnectedBanner({
  auth,
  onDisconnect,
  disconnecting,
}: {
  auth: { method: AuthMethod; username: string };
  onDisconnect: () => void;
  disconnecting: boolean;
}) {
  const meta = METHODS.find((m) => m.id === auth.method)!;

  return (
    <div className="flex items-center justify-between px-3 py-2.5 rounded-md bg-emerald-50 border border-emerald-200/80 dark:bg-emerald-950/20 dark:border-emerald-900/40">
      <div className="flex items-center gap-2.5">
        {/* Pulsing dot */}
        <span className="relative flex h-2 w-2 flex-shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <div>
          <p className="text-xs font-medium text-emerald-800 dark:text-emerald-300 leading-none">
            Connected
            {auth.username && (
              <>
                {" "}
                <span className="font-normal opacity-80">as</span>{" "}
                <span className="font-semibold font-mono">{auth.username}</span>
              </>
            )}
          </p>
          <p className="text-[10px] text-emerald-700/70 dark:text-emerald-400/60 mt-0.5 leading-none">
            via {meta.label}
          </p>
        </div>
      </div>
      <button
        onClick={onDisconnect}
        disabled={disconnecting}
        className="flex items-center gap-1 text-xs px-2.5 py-1 rounded border border-emerald-300/60 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-800 dark:text-emerald-400 dark:hover:bg-emerald-900/40 transition-colors disabled:opacity-50"
      >
        {disconnecting ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <LogOut className="w-3 h-3" />
        )}
        Disconnect
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Segmented method selector
// ---------------------------------------------------------------------------

function MethodSelector({
  selected,
  onChange,
  disabled,
}: {
  selected: AuthMethod;
  onChange: (m: AuthMethod) => void;
  disabled?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pillStyle, setPillStyle] = useState({ left: 0, width: 0 });

  // Compute pill position from the active button
  const updatePill = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const btn = container.querySelector<HTMLButtonElement>(`[data-method="${selected}"]`);
    if (!btn) return;
    const containerLeft = container.getBoundingClientRect().left;
    const btnRect = btn.getBoundingClientRect();
    setPillStyle({ left: btnRect.left - containerLeft, width: btnRect.width });
  }, [selected]);

  useEffect(() => {
    updatePill();
  }, [updatePill]);

  return (
    <div
      ref={containerRef}
      className="relative flex items-center gap-0.5 p-0.5 rounded-md bg-muted/50 border border-border/60 w-full"
    >
      {/* Sliding pill */}
      <span
        className="absolute top-0.5 bottom-0.5 rounded bg-background border border-border/60 shadow-[0_1px_2px_rgba(0,0,0,0.06)] transition-all duration-200 ease-out pointer-events-none"
        style={{ left: pillStyle.left, width: pillStyle.width }}
        aria-hidden
      />

      {METHODS.map((m) => (
        <button
          key={m.id}
          data-method={m.id}
          type="button"
          disabled={disabled}
          onClick={() => onChange(m.id)}
          className={`
            relative z-10 flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs font-medium
            transition-colors duration-150 select-none
            ${selected === m.id
              ? "text-foreground"
              : "text-muted-foreground hover:text-foreground"
            }
            disabled:opacity-40 disabled:cursor-not-allowed
          `}
        >
          {m.icon}
          <span className="hidden sm:inline">{m.label}</span>
          <span className="sm:hidden">{m.shortLabel}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-method field panels
// ---------------------------------------------------------------------------

function PasswordFields({
  fields,
  setField,
  onSubmit,
}: {
  fields: Record<string, string>;
  setField: (k: string, v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label>Username</Label>
        <Input
          value={fields.username ?? ""}
          onChange={(v) => setField("username", v)}
          placeholder="JDOE"
          autoFocus
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
        />
      </div>
      <div>
        <Label>Password</Label>
        <Input
          type="password"
          value={fields.password ?? ""}
          onChange={(v) => setField("password", v)}
          placeholder="••••••••"
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
        />
      </div>
    </div>
  );
}

function PrivateKeyFields({
  fields,
  setField,
  hasExistingKey,
}: {
  fields: Record<string, string>;
  setField: (k: string, v: string) => void;
  hasExistingKey?: boolean;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label>Username</Label>
        <Input
          value={fields.username ?? ""}
          onChange={(v) => setField("username", v)}
          placeholder="JDOE"
          autoFocus
        />
      </div>
      <div>
        <div className="flex items-center justify-between mb-1">
          <Label>Private Key (PEM)</Label>
          <span className="text-[10px] text-muted-foreground/60">RSA or PKCS8</span>
        </div>
        <Textarea
          value={fields.private_key ?? ""}
          onChange={(v) => setField("private_key", v)}
          placeholder={"-----BEGIN RSA PRIVATE KEY-----\n…\n-----END RSA PRIVATE KEY-----"}
          rows={7}
        />
        {hasExistingKey && !fields.private_key && (
          <p className="text-[11px] text-emerald-600/80 dark:text-emerald-400/70 mt-1 flex items-center gap-1">
            <span>✓</span> Key saved — paste a new key above to rotate it.
          </p>
        )}
      </div>
      <div>
        <div className="flex items-center justify-between mb-1">
          <Label>Passphrase</Label>
          <span className="text-[10px] text-muted-foreground/60">optional</span>
        </div>
        <Input
          type="password"
          value={fields.private_key_passphrase ?? ""}
          onChange={(v) => setField("private_key_passphrase", v)}
          placeholder="Key passphrase if encrypted"
        />
      </div>
    </div>
  );
}

function SsoFields({
  fields,
  setField,
  onSubmit,
  busy,
}: {
  fields: Record<string, string>;
  setField: (k: string, v: string) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label>Your Snowflake username (your email, e.g. you@company.com)</Label>
        <Input
          value={fields.username ?? ""}
          onChange={(v) => setField("username", v)}
          placeholder="you@company.com — NOT the Snowflake URL"
          autoFocus
          onKeyDown={(e) => e.key === "Enter" && !busy && onSubmit()}
        />
      </div>
      {/* Browser-launch affordance */}
      <div className="flex items-start gap-2 text-xs text-muted-foreground/70 bg-muted/30 rounded-md px-3 py-2.5 border border-border/40">
        <ExternalLink className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-muted-foreground/50" />
        <p className="leading-relaxed">
          Clicking <em>Sign in</em> will open your default browser where your identity provider
          (Okta, Azure AD, etc.) will handle authentication.
        </p>
      </div>
    </div>
  );
}

function PatFields({
  fields,
  setField,
  onSubmit,
}: {
  fields: Record<string, string>;
  setField: (k: string, v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center justify-between mb-1">
          <Label>Programmatic Access Token</Label>
          <a
            href="https://docs.snowflake.com/en/user-guide/programmatic-access-tokens"
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-primary hover:underline flex items-center gap-0.5"
            tabIndex={-1}
          >
            Docs <ExternalLink className="w-2.5 h-2.5" />
          </a>
        </div>
        <Textarea
          value={fields.token ?? ""}
          onChange={(v) => setField("token", v)}
          placeholder="Paste your PAT here"
          rows={4}
        />
        <p className="text-[10px] text-muted-foreground/60 mt-1.5">
          Generate from Snowsight › Profile › Programmatic access tokens.
        </p>
      </div>
      <div>
        <Label>Username (optional)</Label>
        <Input
          value={fields.username ?? ""}
          onChange={(v) => setField("username", v)}
          placeholder="JDOE — leave blank to infer from token"
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
        />
      </div>
    </div>
  );
}

function OAuthAppFields({
  fields,
  setField,
  expanded,
  setExpanded,
}: {
  fields: Record<string, string>;
  setField: (k: string, v: string) => void;
  expanded: boolean;
  setExpanded: (v: boolean) => void;
}) {
  return (
    <div className="space-y-3">
      {/* Brief explainer */}
      <div className="flex items-start gap-2 text-xs text-muted-foreground/70 bg-muted/30 rounded-md px-3 py-2.5 border border-border/40">
        <Shield className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-muted-foreground/50" />
        <p className="leading-relaxed">
          For server deployments where SSO isn't available. Register a connected app in Snowflake
          and paste the credentials below.{" "}
          <a
            href="https://docs.snowflake.com/en/user-guide/oauth-custom"
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline inline-flex items-center gap-0.5"
          >
            Setup guide <ExternalLink className="w-2.5 h-2.5" />
          </a>
        </p>
      </div>

      <div>
        <Label>Client ID</Label>
        <Input
          value={fields.client_id ?? ""}
          onChange={(v) => setField("client_id", v)}
          placeholder="0oa…"
          autoFocus
        />
      </div>
      <div>
        <Label>Client Secret</Label>
        <Input
          type="password"
          value={fields.client_secret ?? ""}
          onChange={(v) => setField("client_secret", v)}
          placeholder="••••••••"
        />
      </div>

      {/* Advanced toggle */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        Advanced options
      </button>
      {expanded && (
        <div>
          <Label>Redirect URI</Label>
          <Input
            value={fields.redirect_uri ?? ""}
            onChange={(v) => setField("redirect_uri", v)}
            placeholder="https://your-server.example.com/oauth/callback"
          />
          <p className="text-[10px] text-muted-foreground/60 mt-1.5">
            Leave blank to use the default callback registered in your app.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connect button
// ---------------------------------------------------------------------------

function ConnectButton({
  method,
  loading,
  disabled,
  onClick,
}: {
  method: AuthMethod;
  loading: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  const LABELS: Record<AuthMethod, [string, string]> = {
    password:   ["Connect",               "Connecting…"],
    privatekey: ["Connect with Key",      "Connecting…"],
    sso:        ["Sign in with SSO",      "Opening browser…"],
    pat:        ["Connect with Token",    "Connecting…"],
    oauth:      ["Authorize & Connect",   "Connecting…"],
  };

  const [idle, busy] = LABELS[method];

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className="flex items-center justify-center gap-1.5 w-full text-xs px-3 py-2 rounded-md
                 bg-primary text-primary-foreground hover:bg-primary/90
                 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-medium"
    >
      {loading ? (
        <>
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          {busy}
        </>
      ) : (
        <>
          {method === "sso" && <ExternalLink className="w-3.5 h-3.5" />}
          {method === "password" && <Lock className="w-3.5 h-3.5" />}
          {method === "privatekey" && <Key className="w-3.5 h-3.5" />}
          {method === "pat" && <Fingerprint className="w-3.5 h-3.5" />}
          {method === "oauth" && <Shield className="w-3.5 h-3.5" />}
          {idle}
        </>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SnowflakeAuthSection({ connectedAuth, onConnect, onDisconnect }: Props) {
  // Initialise selector to the active method, or "sso" as a sensible default
  const [selectedMethod, setSelectedMethod] = useState<AuthMethod>(
    (connectedAuth?.method as AuthMethod) ?? "sso"
  );
  // Pre-fill username from the active connection so the user sees who's configured.
  const [fields, setFields] = useState<Record<string, string>>(
    connectedAuth?.username ? { username: connectedAuth.username } : {}
  );
  const [loading, setLoading] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oauthAdvanced, setOauthAdvanced] = useState(false);

  // Reset field state when switching methods
  const handleMethodChange = (m: AuthMethod) => {
    setSelectedMethod(m);
    setFields({});
    setError(null);
  };

  const setField = (k: string, v: string) => {
    setFields((prev) => ({ ...prev, [k]: v }));
  };

  const handleConnect = async () => {
    setError(null);
    setLoading(true);
    try {
      await onConnect(selectedMethod, fields);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setError(null);
    setDisconnecting(true);
    try {
      await onDisconnect();
    } catch (e) {
      setError(String(e));
    } finally {
      setDisconnecting(false);
    }
  };

  // Compute whether the connect button should be enabled
  const isConnectDisabled = (() => {
    if (loading) return true;
    switch (selectedMethod) {
      case "password":
        return !fields.username?.trim() || !fields.password?.trim();
      case "privatekey":
        return !fields.username?.trim() || !fields.private_key?.trim();
      case "sso":
        return !fields.username?.trim();
      case "pat":
        return !fields.token?.trim();
      case "oauth":
        return !fields.client_id?.trim() || !fields.client_secret?.trim();
    }
  })();

  const isConnected = !!connectedAuth;
  const meta = METHODS.find((m) => m.id === selectedMethod)!;

  return (
    <div className="space-y-3">
      {/* Section heading */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Lock className="w-3 h-3 text-muted-foreground" />
          <span className="text-xs font-medium text-muted-foreground">Authentication</span>
        </div>
        {isConnected && connectedAuth.method !== selectedMethod && (
          <span className="text-[10px] text-amber-600/80 dark:text-amber-400/70">
            Switching method will disconnect the active session
          </span>
        )}
      </div>

      {/* Active connection banner */}
      {isConnected && (
        <ConnectedBanner
          auth={connectedAuth}
          onDisconnect={handleDisconnect}
          disconnecting={disconnecting}
        />
      )}

      {/* Method selector — always visible for easy switching */}
      <MethodSelector
        selected={selectedMethod}
        onChange={handleMethodChange}
        disabled={loading || disconnecting}
      />

      {/* Method description */}
      <p className="text-[11px] text-muted-foreground/70 leading-relaxed px-0.5">
        {meta.description}
        {meta.hint && (
          <>
            {" "}
            <span className="text-muted-foreground/50">{meta.hint}</span>
          </>
        )}
      </p>

      {/* Credential fields — fade in on method change */}
      <div className="space-y-3 animate-in fade-in duration-150">
        {selectedMethod === "password" && (
          <PasswordFields fields={fields} setField={setField} onSubmit={handleConnect} />
        )}
        {selectedMethod === "privatekey" && (
          <PrivateKeyFields
            fields={fields}
            setField={setField}
            hasExistingKey={connectedAuth?.method === "privatekey"}
          />
        )}
        {selectedMethod === "sso" && (
          <SsoFields
            fields={fields}
            setField={setField}
            onSubmit={handleConnect}
            busy={loading}
          />
        )}
        {selectedMethod === "pat" && (
          <PatFields fields={fields} setField={setField} onSubmit={handleConnect} />
        )}
        {selectedMethod === "oauth" && (
          <OAuthAppFields
            fields={fields}
            setField={setField}
            expanded={oauthAdvanced}
            setExpanded={setOauthAdvanced}
          />
        )}
      </div>

      {/* Error */}
      {error && <ErrorBanner message={error} />}

      {/* Connect CTA */}
      <ConnectButton
        method={selectedMethod}
        loading={loading}
        disabled={isConnectDisabled}
        onClick={handleConnect}
      />
    </div>
  );
}
