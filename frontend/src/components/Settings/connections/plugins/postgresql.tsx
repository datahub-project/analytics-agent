import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "host",     label: "Host",     placeholder: "localhost",  required: true },
  { key: "port",     label: "Port",     placeholder: "5432" },
  { key: "database", label: "Database", placeholder: "my_database", required: true },
  { key: "user",     label: "Username", placeholder: "db_user" },
  { key: "password", label: "Password", type: "password" as const, placeholder: "••••••••" },
];

export const postgresqlPlugin: ConnectionPlugin = {
  id: "postgresql",
  serviceId: "postgresql",
  label: "PostgreSQL",
  category: "engine",
  transport: "native",
  description: "Connect to a PostgreSQL database",
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={(payload: NewConnectionPayload) =>
        onDone({ ...payload, config: { dialect: "postgresql+psycopg2", ...payload.config } })
      }
    />
  ),
};
