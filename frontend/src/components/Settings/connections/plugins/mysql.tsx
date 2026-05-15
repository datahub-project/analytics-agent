import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin, NewConnectionPayload } from "../types";

const FIELDS = [
  { key: "host",     label: "Host",     placeholder: "localhost",  required: true },
  { key: "port",     label: "Port",     placeholder: "3306" },
  { key: "database", label: "Database", placeholder: "my_database", required: true },
  { key: "user",     label: "Username", placeholder: "db_user" },
  { key: "password", label: "Password", type: "password" as const, placeholder: "••••••••" },
];

export const mysqlPlugin: ConnectionPlugin = {
  id: "mysql",
  serviceId: "mysql",
  label: "MySQL",
  category: "engine",
  transport: "native",
  description: "Connect to a MySQL or MariaDB database",
  fields: FIELDS,
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={(payload: NewConnectionPayload) =>
        onDone({ ...payload, config: { dialect: "mysql+pymysql", ...payload.config } })
      }
    />
  ),
};
