import { useState } from "react";
import { CheckCircle2, FlaskConical, Loader2, XCircle } from "lucide-react";
import { testConnectorConfig } from "@/api/settings";
import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "project",          label: "GCP Project ID",      placeholder: "my-gcp-project", required: true },
  { key: "dataset",          label: "Default Dataset",      placeholder: "my_dataset" },
  {
    key: "credentials_json", label: "Service Account JSON", type: "json" as const,
    placeholder: '{"type":"service_account","project_id":"..."}',
    hint: "Paste your GCP service account key JSON. Saved encrypted.",
  },
];

function BigQueryForm({
  onDone,
  onCancel,
}: {
  onDone: (payload: NewConnectionPayload) => void;
  onCancel: () => void;
}) {
  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "error">("idle");
  const [testMsg, setTestMsg] = useState("");

  const handleTest = async (values: Record<string, string>) => {
    setTestState("testing");
    setTestMsg("");
    try {
      const { config, secrets } = splitSecrets(values);
      const result = await testConnectorConfig("bigquery", config, secrets);
      setTestState(result.ok ? "ok" : "error");
      setTestMsg(result.message);
    } catch (e: unknown) {
      setTestState("error");
      setTestMsg(e instanceof Error ? e.message : "Test failed");
    }
  };

  return (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={onDone}
      extraActions={(values, name) => (
        <div className="flex items-center gap-2 flex-1">
          <button
            type="button"
            disabled={testState === "testing" || !values.project?.trim()}
            onClick={() => handleTest(values)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors disabled:opacity-50"
          >
            {testState === "testing"
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <FlaskConical className="w-3.5 h-3.5" />}
            Test
          </button>
          {testState === "ok" && (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <CheckCircle2 className="w-3.5 h-3.5" />{testMsg}
            </span>
          )}
          {testState === "error" && (
            <span className="flex items-center gap-1 text-xs text-destructive">
              <XCircle className="w-3.5 h-3.5" />{testMsg}
            </span>
          )}
        </div>
      )}
    />
  );
}

function splitSecrets(values: Record<string, string>) {
  const secretKeys = new Set(["credentials_json"]);
  const config: Record<string, string> = {};
  const secrets: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (secretKeys.has(k)) secrets[k] = v;
    else config[k] = v;
  }
  return { config, secrets };
}

export const bigqueryPlugin: ConnectionPlugin = {
  id: "bigquery",
  serviceId: "bigquery",
  label: "BigQuery",
  category: "engine",
  transport: "native",
  description: "Connect to Google BigQuery",
  fields: FIELDS,
  Form: BigQueryForm,
};
