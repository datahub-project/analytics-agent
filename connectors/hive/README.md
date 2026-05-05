# analytics-agent-connector-hive

Hive / Apache Kyuubi / Spark Thrift Server MCP connector for [Analytics Agent](https://github.com/datahub-project/analytics-agent).

Installed automatically when you add a Hive data source in the Analytics Agent UI. Can also be installed manually:

```bash
uv tool install analytics-agent-connector-hive
```

## Configuration

All configuration is read from environment variables set by the analytics-agent core when it launches the connector subprocess.

| Variable | Default | Description |
|---|---|---|
| `HIVE_HOST` | *(required)* | HiveServer2 / Kyuubi host |
| `HIVE_PORT` | `10000` | HiveServer2 port |
| `HIVE_DATABASE` | `default` | Default database |
| `HIVE_AUTH` | `NONE` | Auth mode: `NONE`, `NOSASL`, `LDAP`, `PLAIN`, `KERBEROS` |
| `HIVE_USER` | | Username (required for LDAP/PLAIN, recommended for KERBEROS) |
| `HIVE_PASSWORD` | | Password (LDAP/PLAIN only) |
| `HIVE_KERBEROS_SERVICE_NAME` | `hive` | Kerberos service principal prefix |
| `SQL_ROW_LIMIT` | `500` | Maximum rows returned per query |

## Auth modes

- **NONE / NOSASL** — no credentials needed; typical for local or trusted-network deployments
- **LDAP / PLAIN** — username + password
- **KERBEROS** — requires `kerberos` system library (`brew install krb5` / `apt-get install libkrb5-dev`)
