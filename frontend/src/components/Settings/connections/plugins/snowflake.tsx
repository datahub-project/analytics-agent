import { useState } from "react";
import { parseSnowflakeAccount, browserSso } from "@/api/oauth";
import { SnowflakeAuthSection } from "../../SnowflakeAuthSection";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const INPUT_CLASS =
  "w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono " +
  "focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/40";

function SnowflakeForm({
  onDone,
  onCancel,
}: {
  onDone: (payload: NewConnectionPayload) => void;
  onCancel: () => void;
}) {
  const [name, setName]       = useState("");
  const [label, setLabel]     = useState("");
  const [account, setAccount] = useState("");
  const [user, setUser]       = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [database, setDatabase]   = useState("");
  const [schema, setSchema]       = useState("");
  const [error, setError]     = useState<string | null>(null);

  // Called by SnowflakeAuthSection when user clicks "Connect with Key" / "Sign in" / etc.
  // For "Add new" this IS the save action — we bundle config + credentials together.
  const handleConnect = async (method: string, fields: Record<string, string>) => {
    if (!name.trim() || !account.trim()) {
      setError("Name and Snowflake account are required.");
      return;
    }
    setError(null);

    const config: Record<string, string> = {
      account,
      user:      fields.username || user,
      warehouse,
      database,
      schema,
    };

    // Credentials go into config so build_mcp_config can pass them to the subprocess env.
    let postCreate: ((n: string) => Promise<void>) | undefined;

    if (method === "privatekey") {
      if (fields.private_key) config.private_key = fields.private_key;
    } else if (method === "password") {
      if (fields.password) config.password = fields.password;
    } else if (method === "pat") {
      if (fields.token)    config.pat_token = fields.token;
    } else if (method === "sso") {
      postCreate = async (connName: string) => {
        await browserSso(connName, parseSnowflakeAccount(account), fields.username);
      };
    }

    await onDone({ name: name.trim(), label: label.trim() || undefined, config, postCreate });
  };

  return (
    <div className="space-y-3">
      {/* Name + optional label */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-snowflake"
            className={INPUT_CLASS}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Label</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Display label (optional)"
            className={INPUT_CLASS.replace("font-mono", "")}
          />
        </div>
      </div>

      {/* Connection config */}
      {[
        { key: "account",   val: account,   set: setAccount,   label: "Snowflake URL or Account ID", required: true,  placeholder: "https://app.snowflake.com/org/acct  or  acct-12345" },
        { key: "user",      val: user,      set: setUser,      label: "Service user (override in auth below)", required: false, placeholder: "SVC_ANALYTICS_USER" },
        { key: "warehouse", val: warehouse, set: setWarehouse, label: "Warehouse",  required: false, placeholder: "COMPUTE_WH" },
        { key: "database",  val: database,  set: setDatabase,  label: "Database",   required: false, placeholder: "PROD" },
        { key: "schema",    val: schema,    set: setSchema,    label: "Schema",     required: false, placeholder: "PUBLIC" },
      ].map((f) => (
        <div key={f.key} className="space-y-1">
          <label className="text-xs text-muted-foreground">
            {f.label}
            {f.required && <span className="text-red-400 ml-0.5">*</span>}
          </label>
          <input
            type="text"
            value={f.val}
            onChange={(e) => f.set(e.target.value)}
            placeholder={f.placeholder}
            className={INPUT_CLASS}
          />
        </div>
      ))}

      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* Auth section — same component as the edit view */}
      <SnowflakeAuthSection
        connectedAuth={null}
        onConnect={handleConnect}
        onDisconnect={async () => {}}
      />

      {/* Cancel sits outside the auth section */}
      <button
        type="button"
        onClick={onCancel}
        className="text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors"
      >
        Cancel
      </button>
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
