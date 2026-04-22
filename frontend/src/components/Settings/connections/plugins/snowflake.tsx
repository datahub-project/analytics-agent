import { useState } from "react";
import { KeyRound, Loader2, LogIn } from "lucide-react";
import { browserSso, parseSnowflakeAccount } from "@/api/oauth";
import type { ConnectionPlugin } from "../types";
import { SimpleFormShell } from "../SimpleFormShell";

function SnowflakeForm({
  onDone,
  onCancel,
}: {
  onDone: (payload: import("../types").NewConnectionPayload) => void;
  onCancel: () => void;
}) {
  const [ssoUser, setSsoUser] = useState("");
  const [ssoStep, setSsoStep] = useState(false);

  return (
    <SimpleFormShell
      fields={[
        {
          key: "account",
          label: "Snowflake URL or Account ID",
          type: "mono",
          placeholder: "https://app.snowflake.com/org/acct  or  acct-12345",
          required: true,
        },
        { key: "user", label: "Service user", placeholder: "svc_user" },
        { key: "warehouse", label: "Warehouse", placeholder: "COMPUTE_WH" },
        { key: "database", label: "Database", placeholder: "PROD" },
        { key: "schema", label: "Schema", placeholder: "PUBLIC" },
      ]}
      onCancel={onCancel}
      onDone={onDone}
      extraActions={(values, name) => (
        <div className="flex items-center gap-2 flex-wrap">
          {/* SSO username row */}
          <div className="flex items-center gap-1.5 border-l border-border/40 pl-2">
            <KeyRound className="w-3 h-3 text-muted-foreground/60 flex-shrink-0" />
            <input
              type="text"
              value={ssoUser}
              onChange={(e) => setSsoUser(e.target.value)}
              placeholder="SSO email"
              className="text-xs bg-background border border-border rounded px-2 py-1 w-36 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              type="button"
              disabled={ssoStep || !name || !ssoUser.trim()}
              onClick={async () => {
                setSsoStep(true);
                try {
                  const parsed = values.account ? parseSnowflakeAccount(values.account) : undefined;
                  await onDone({
                    name,
                    config: values,
                    postCreate: async (connName) => {
                      await browserSso(connName, parsed, ssoUser.trim() || undefined);
                    },
                  });
                } finally {
                  setSsoStep(false);
                }
              }}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors disabled:opacity-50"
            >
              {ssoStep ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <LogIn className="w-3.5 h-3.5" />
              )}
              SSO
            </button>
          </div>
        </div>
      )}
    />
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
