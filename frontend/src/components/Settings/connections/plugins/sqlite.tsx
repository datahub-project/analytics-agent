import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "database", label: "Database file path", type: "mono" as const,
    placeholder: "/absolute/path/to/database.db", required: true },
];

export const sqlitePlugin: ConnectionPlugin = {
  id: "sqlite",
  serviceId: "sqlite",
  label: "SQLite",
  category: "engine",
  transport: "native",
  description: "Connect to a local SQLite database file",
  fields: FIELDS,
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={(payload: NewConnectionPayload) =>
        onDone({ ...payload, config: { dialect: "sqlite", ...payload.config } })
      }
    />
  ),
};
