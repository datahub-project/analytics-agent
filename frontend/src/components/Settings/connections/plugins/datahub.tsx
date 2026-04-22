import type { FieldDef } from "../types";
import { createSimplePlugin } from "../helpers";

/** Canonical field definitions for a native DataHub connection.
 *  Imported by the onboarding wizard so the labels/placeholders stay in sync. */
export const datahubConnectionFields: FieldDef[] = [
  {
    key: "url",
    label: "GMS URL",
    type: "mono",
    placeholder: "https://your-instance.acryl.io/gms",
    required: true,
  },
  {
    key: "token",
    label: "Access token",
    type: "password",
    placeholder: "eyJhbGci…",
    required: true,
  },
];

export const datahubPlugin = createSimplePlugin({
  id: "datahub",
  serviceId: "datahub",
  label: "DataHub",
  category: "context_platform",
  description: "Direct connection to DataHub metadata & governance",
  fields: datahubConnectionFields,
});
