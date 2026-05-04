import { useState } from "react";
import { ChevronDown, ChevronUp, Eye, EyeOff, ExternalLink, Fingerprint, Key, Lock, LogIn, Shield } from "lucide-react";
import { parseSnowflakeAccount, browserSso } from "@/api/oauth";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

type AuthMethod = "privatekey" | "password" | "sso" | "pat" | "oauth";

const METHODS: { id: AuthMethod; label: string; icon: React.ReactNode }[] = [
  { id: "password",   label: "Password",    icon: <Lock className="w-3 h-3" /> },
  { id: "privatekey", label: "Private Key", icon: <Key className="w-3 h-3" /> },
  { id: "sso",        label: "SSO",         icon: <LogIn className="w-3 h-3" /> },
  { id: "pat",        label: "PAT",         icon: <Fingerprint className="w-3 h-3" /> },
  { id: "oauth",      label: "OAuth App",   icon: <Shield className="w-3 h-3" /> },
];

const BASE =
  "w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 " +
  "focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/40";

function Field({ label, hint, children }: { label: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">{label}</label>
        {hint && <span className="text-[10px] text-muted-foreground/50">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function PasswordInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} className={BASE + " font-mono pr-8"} />
      <button type="button" onClick={() => setShow((v) => !v)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground">
        {show ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
      </button>
    </div>
  );
}

function SnowflakeForm({ onDone, onCancel }: { onDone: (p: NewConnectionPayload) => void; onCancel: () => void }) {
  const [name, setName]       = useState("");
  const [account, setAccount] = useState("");
  const [method, setMethod]   = useState<AuthMethod>("privatekey");

  // Per-method credential fields
  const [username, setUsername]   = useState("");
  const [password, setPassword]   = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [patToken, setPatToken]   = useState("");
  const [clientId, setClientId]   = useState("");
  const [clientSecret, setClientSecret] = useState("");

  // Advanced (optional)
  const [showAdv, setShowAdv] = useState(false);
  const [warehouse, setWarehouse] = useState("");
  const [database, setDatabase]   = useState("");
  const [schema, setSchema]       = useState("");

  const [error, setError] = useState<string | null>(null);

  const handleMethodChange = (m: AuthMethod) => { setMethod(m); setError(null); };

  const handleSubmit = async () => {
    if (!name.trim() || !account.trim()) { setError("Name and Account are required."); return; }
    setError(null);

    const config: Record<string, string> = { account, warehouse, database, schema };
    let postCreate: ((n: string) => Promise<void>) | undefined;

    if (method === "privatekey") {
      if (!username.trim() || !privateKey.trim()) { setError("Username and Private Key are required."); return; }
      config.user = username;
      config.private_key = privateKey;
      if (passphrase) config.private_key_passphrase = passphrase;
    } else if (method === "password") {
      if (!username.trim() || !password.trim()) { setError("Username and Password are required."); return; }
      config.user = username;
      config.password = password;
    } else if (method === "sso") {
      if (!username.trim()) { setError("Username (SSO email) is required."); return; }
      config.user = username;
      postCreate = async (connName) => {
        await browserSso(connName, parseSnowflakeAccount(account), username);
      };
    } else if (method === "pat") {
      if (!patToken.trim()) { setError("PAT token is required."); return; }
      config.pat_token = patToken;
      if (username) config.user = username;
    } else if (method === "oauth") {
      if (!clientId.trim() || !clientSecret.trim()) { setError("Client ID and Client Secret are required."); return; }
      config.oauth_client_id = clientId;
      config.oauth_client_secret = clientSecret;
    }

    await onDone({ name: name.trim(), config, postCreate });
  };

  const btnLabel: Record<AuthMethod, string> = {
    privatekey: "Connect with Key",
    password:   "Connect",
    sso:        "Sign in with SSO",
    pat:        "Connect with Token",
    oauth:      "Authorize & Connect",
  };

  return (
    <div className="space-y-3">
      {/* Name + Account — always required */}
      <div className="grid grid-cols-2 gap-2">
        <Field label={<>Name <span className="text-red-400">*</span></>}>
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="my-snowflake" className={BASE + " font-mono"} />
        </Field>
        <Field label={<>Account <span className="text-red-400">*</span></>}>
          <input value={account} onChange={(e) => setAccount(e.target.value)}
            placeholder="acct-12345 or app URL" className={BASE + " font-mono"} />
        </Field>
      </div>

      {/* Auth method tabs */}
      <div className="flex gap-0.5 p-0.5 rounded-md bg-muted/50 border border-border/60">
        {METHODS.map((m) => (
          <button key={m.id} type="button" onClick={() => handleMethodChange(m.id)}
            className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-xs rounded transition-colors
              ${method === m.id ? "bg-background border border-border/60 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            {m.icon}
            <span className="hidden sm:inline">{m.label}</span>
          </button>
        ))}
      </div>

      {/* Method-specific fields */}
      {method === "privatekey" && <>
        <Field label="Username"><input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="SVC_USER" className={BASE + " font-mono"} autoFocus /></Field>
        <Field label="Private Key (PEM)" hint="RSA or PKCS8">
          <textarea value={privateKey} onChange={(e) => setPrivateKey(e.target.value)} rows={6} spellCheck={false}
            placeholder={"-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----"}
            className={BASE + " font-mono resize-y leading-relaxed"} />
        </Field>
        <Field label="Passphrase" hint="optional"><PasswordInput value={passphrase} onChange={setPassphrase} placeholder="Key passphrase if encrypted" /></Field>
      </>}

      {method === "password" && <>
        <Field label="Username"><input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="SVC_USER" className={BASE + " font-mono"} autoFocus /></Field>
        <Field label="Password"><PasswordInput value={password} onChange={setPassword} placeholder="••••••••" /></Field>
      </>}

      {method === "sso" && <>
        <Field label="Your Snowflake email">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="you@company.com" className={BASE} autoFocus />
        </Field>
        <div className="flex items-start gap-2 text-xs text-muted-foreground/70 bg-muted/30 rounded px-3 py-2.5 border border-border/40">
          <ExternalLink className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-muted-foreground/50" />
          <p>Clicking <em>Sign in</em> will open your browser — Okta, Azure AD, or another IdP will handle auth.</p>
        </div>
      </>}

      {method === "pat" && <>
        <Field label="Programmatic Access Token">
          <textarea value={patToken} onChange={(e) => setPatToken(e.target.value)} rows={3} spellCheck={false}
            placeholder="Paste your PAT here"
            className={BASE + " font-mono resize-none leading-relaxed"} autoFocus />
        </Field>
        <Field label="Username" hint="optional — leave blank to infer from token">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="SVC_USER" className={BASE + " font-mono"} />
        </Field>
      </>}

      {method === "oauth" && <>
        <Field label="Client ID"><input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="0oa…" className={BASE + " font-mono"} autoFocus /></Field>
        <Field label="Client Secret"><PasswordInput value={clientSecret} onChange={setClientSecret} placeholder="••••••••" /></Field>
      </>}

      {/* Advanced — warehouse / database / schema */}
      <button type="button" onClick={() => setShowAdv((v) => !v)}
        className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-muted-foreground transition-colors">
        {showAdv ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        Advanced — warehouse, database, schema
      </button>
      {showAdv && (
        <div className="grid grid-cols-3 gap-2 pt-0.5">
          {[["Warehouse", warehouse, setWarehouse, "COMPUTE_WH"], ["Database", database, setDatabase, "PROD"], ["Schema", schema, setSchema, "PUBLIC"]].map(([lbl, val, set, ph]) => (
            <Field key={lbl as string} label={lbl as string}>
              <input value={val as string} onChange={(e) => (set as (v: string) => void)(e.target.value)} placeholder={ph as string} className={BASE + " font-mono"} />
            </Field>
          ))}
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-2 justify-end pt-1">
        <button type="button" onClick={onCancel}
          className="text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors">Cancel</button>
        <button type="button" onClick={handleSubmit}
          className="text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
          {btnLabel[method]}
        </button>
      </div>
    </div>
  );
}

export const snowflakePlugin: ConnectionPlugin = {
  id: "snowflake",
  serviceId: "snowflake",
  label: "Snowflake",
  category: "engine",
  transport: "native",
  description: "Direct connection to Snowflake cloud data warehouse",
  Form: SnowflakeForm,
};
