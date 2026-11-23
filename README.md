# Python Autoscaling on Railway

A stateless Python HTTP application and a separate Python controller for exploring vertical resource use and horizontal replica scaling on Railway. Both use Python's standard library and the same Docker image.

The application exposes a bounded I/O-style workload. The controller samples in-flight requests, estimates load per replica, and changes regional replica count through Railway's Public API, using the environment-patch flow used by the current CLI. The public demonstration page shows actual observations and scaling decisions without exposing credentials.

## What runs

- `api`: HTTP application, health endpoint, protected load endpoint, and a read-only demonstration page.
- `autoscaler`: one controller replica, a private health/status endpoint, and an environment-scoped Railway project token that you supply after deployment.

The initial configuration uses one API replica and one controller. The controller starts in observe/dry-run mode. No database or volume is required. Both services incur resource usage; additional API replicas also consume resources.

## Deploy and configure

Use an appropriate Railway account/plan. The [.railway/railway.ts](.railway/railway.ts) file declares the two services, Docker build, start commands, health checks, private status link, and resource ceilings using Railway IaC. The marketplace template provides the initial public API domain and generated shared measurement secret.

If applying IaC directly, generate a cryptographically random measurement secret, set it as `METRICS_TOKEN` on `api`, and add the API's public domain before deploying the controller. The IaC file preserves secrets configured in Railway; it does not put a reusable password in source code. The published template handles measurement-secret generation for each deployment.

After deployment:

1. Open the API's public URL and check `/health`.
2. Create a project token for this project's deployed environment in the project's token settings. Supply it as `RAILWAY_API_TOKEN` on `autoscaler`. Do not put an account token in source code.
3. Confirm `TARGET_SERVICE_ID` points to `api`, `TARGET_LOAD_URL` points to its `/_load` path, and `METRICS_TOKEN` references the API's generated value. The template uses service references for these settings.
4. Keep `SCALING_ENABLED=false` and `DRY_RUN=true` while checking observations. Set `SCALING_ENABLED=true` and `DRY_RUN=false`, then deploy the controller when you are ready to apply changes.
5. Keep exactly one controller replica. The controller refuses to scale when its configured replica count differs from one.

The project token authenticates with `Project-Access-Token`. An account/workspace token uses a different header and should not be substituted into this example.

## Generate a bounded workload

Run only against a service you own:

```sh
python3 load.py 'https://YOUR-API.up.railway.app/work?ms=1000' --seconds 120 --concurrency 12
```

The runner accepts at most 300 seconds, 24 concurrent workers, and 10,000 attempts. A worker stops after five consecutive failures. It reports successful requests, error types, p95 duration, and replica identities that actually served requests. The workload waits for the requested interval and holds a small allocation during each active request, so you can inspect CPU and RAM separately from replica count.

Watch the public demonstration page or controller logs. Under sustained demand, configured capacity should rise within the allowed bounds. After traffic stops, the longer low-demand window allows gradual scale-down. Confirm that requests were served by additional replica identities, not just that a settings mutation returned success.

## Default policy

| Setting | Default | Meaning |
| --- | --- | --- |
| `MIN_REPLICAS` | `1` | Minimum API count; choose production redundancy deliberately |
| `MAX_REPLICAS` | `3` | Maximum API count; must fit your plan |
| `TARGET_INFLIGHT` | `4` | Demonstration load target per replica, not a universal tuning recommendation |
| `POLL_SECONDS` | `5` | Minimum interval between evaluations, excluding slow requests |
| `SCALE_UP_WINDOW_SECONDS` | `10` | Sustained demand before increasing capacity |
| `SCALE_DOWN_WINDOW_SECONDS` | `60` | Sustained low demand before decreasing capacity |
| `COOLDOWN_SECONDS` | `30` | Wait after a change, reconciliation, or controller restart |

Changes move one replica at a time. The controller waits for observations to match the requested count before making another decision. Missing/stale/invalid measurements and API errors hold capacity and reset the demand window; failed requests are not interpreted as zero load. API/measurement errors use bounded backoff. Each evaluation records its reason.

The controller reads the configured target region from the environment configuration and commits only that service’s regional replica count. It refuses multi-region targets. It does not rely on the legacy service-instance `numReplicas` field. See [the CLI scaling documentation](https://docs.railway.com/cli/scale) and [its implementation](https://github.com/railwayapp/cli/blob/v5.71.0/src/commands/scale.rs).

## Measurement and operating boundaries

This version starts with a single-region stateless service. It samples an authenticated endpoint behind Railway's public routing. A sample describes one responding replica; multiple samples and a recent identity window estimate per-replica load and check the observed count. A shared queue or independently aggregated metric may suit other workloads better.

The history and decisions shown by the controller are in memory and reset on a controller deployment. A restart begins a fresh cooldown. Keep one active controller, leave Serverless off for this continuously polled workload, and avoid competing manual/IaC replica changes while automation is active. Replica bounds and resource ceilings are capacity controls, not an invoice guarantee. Use Railway usage alerts and the spending controls appropriate to your availability requirements.

Stop the demonstration deployments when finished. Retain production capacity and recovery controls required by your application.

## Local checks

Python 3.11 or newer:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile api.py autoscaler.py policy.py load.py
```

Optional IaC type check with Node.js and npm:

```sh
npm ci
npm run check
```

## Sources

- [Railway horizontal autoscaling guide](https://railway.com/guides/autoscale-horizontally)
- [Scaling reference](https://docs.railway.com/deployments/scaling)
- [Service-instance API operations](https://docs.railway.com/integrations/api/manage-services)
- [API authentication](https://docs.railway.com/integrations/api)
- [Cost controls](https://docs.railway.com/pricing/cost-control)
