import { createMcpSsePlugin } from "../helpers";

export const snowflakeMcpPlugin = createMcpSsePlugin({
  id: "snowflake-mcp",
  serviceId: "snowflake",
  label: "Snowflake via MCP",
  category: "engine",
  description: "Connect to Snowflake through a Snowflake MCP server",
  extraFields: [
    { key: "account", label: "Snowflake account", type: "mono", placeholder: "acct-12345" },
  ],
});
