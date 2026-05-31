import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "database", label: "Database file path", type: "mono" as const,
    placeholder: "/absolute/path/to/database.duckdb", required: true },
];

export const duckdbPlugin: ConnectionPlugin = {
  id: "duckdb",
  serviceId: "duckdb",
  label: "DuckDB",
  category: "engine",
  transport: "native",
  description: "Connect to a local DuckDB database file",
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={(payload: NewConnectionPayload) =>
        onDone({ ...payload, config: { dialect: "duckdb", ...payload.config } })
      }
    />
  ),
};
