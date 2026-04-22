export type { ConnectionPlugin, ConnectionCategory, ConnectionTransport, NewConnectionPayload, FieldDef } from "./types";
export { AddConnectionFlow } from "./AddConnectionFlow";

import { snowflakePlugin } from "./plugins/snowflake";
import { snowflakeMcpPlugin } from "./plugins/snowflake-mcp";
import { mysqlPlugin } from "./plugins/mysql";
import { postgresqlPlugin } from "./plugins/postgresql";
import { sqlitePlugin } from "./plugins/sqlite";
import { datahubPlugin } from "./plugins/datahub";
import { datahubMcpPlugin } from "./plugins/datahub-mcp";
import { customMcpEnginePlugin, customMcpContextPlugin } from "./plugins/custom-mcp";
import type { ConnectionPlugin } from "./types";

// Order determines display order within each category group.
// Native connectors first, MCP variants follow, custom MCP wildcard always last.
export const CONNECTION_PLUGINS: ConnectionPlugin[] = [
  // Engines
  snowflakePlugin,
  snowflakeMcpPlugin,
  mysqlPlugin,
  postgresqlPlugin,
  sqlitePlugin,
  customMcpEnginePlugin,

  // Context platforms
  datahubPlugin,
  datahubMcpPlugin,
  customMcpContextPlugin,
];
