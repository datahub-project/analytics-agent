import { createSimplePlugin } from "../helpers";

export const hivePlugin = createSimplePlugin({
  id: "hive",
  serviceId: "hive",
  label: "Hive / Kyuubi / Spark",
  category: "engine",
  description: "Connect to HiveServer2, Apache Kyuubi, or Spark Thrift Server",
  fields: [
    { key: "host",     label: "Host",     type: "mono", placeholder: "kyuubi-host or localhost", required: true },
    { key: "port",     label: "Port",     type: "mono", placeholder: "10000" },
    { key: "database", label: "Database", type: "mono", placeholder: "default" },
    { key: "auth",     label: "Auth",     type: "mono", placeholder: "NONE  (or NOSASL, LDAP, KERBEROS)" },
    { key: "user",     label: "Username", type: "mono", placeholder: "analytics_user" },
    { key: "password", label: "Password", type: "password", placeholder: "LDAP/PLAIN only" },
  ],
});
