import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "project",          label: "GCP Project ID",       placeholder: "my-gcp-project", required: true },
  { key: "dataset",          label: "Default Dataset",       placeholder: "my_dataset" },
  { key: "credentials_json", label: "Service Account JSON",  type: "password" as const, placeholder: '{"type":"service_account","project_id":"..."}' },
];

export const bigqueryPlugin: ConnectionPlugin = {
  id: "bigquery",
  serviceId: "bigquery",
  label: "BigQuery",
  category: "engine",
  transport: "native",
  description: "Connect to Google BigQuery",
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={(payload: NewConnectionPayload) => onDone(payload)}
    />
  ),
};