# analytics-agent Helm chart

## Bootstrap hook

A `Job` runs `analytics-agent bootstrap` as a `helm.sh/hook: pre-install,pre-upgrade`
hook. It applies Alembic migrations and seeds `config.yaml` entries into the
database before any pod starts.

| Value | Default | Purpose |
|-------|---------|---------|
| `bootstrap.enabled` | `true` | Set to `false` to skip the hook (e.g. when migrations are managed externally). |
| `bootstrap.resources` | `{}` | Resource requests/limits for the bootstrap container. |
| `bootstrap.podAnnotations` | `{}` | Extra annotations on the Job pod. |

The Job uses the same image, secret (`{fullname}-env`), `volumes`, `volumeMounts`,
`nodeSelector`, `tolerations`, and `affinity` as the deployment. It has
`backoffLimit: 0` — failures are immediate and visible via `kubectl logs`.

If a pod starts before the bootstrap hook has run (e.g. you disabled
`bootstrap.enabled` and forgot to migrate externally), the lifespan crashes with
a SQLAlchemy "no such table" error.
