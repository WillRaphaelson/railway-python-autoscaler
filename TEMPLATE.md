# Deploy and Host a Python Autoscaler with Railway

Deploy a stateless Python application and a separate controller that can scale the application's replicas through Railway's Public API.

## About Hosting a Python Autoscaler

The template creates two services from the same public repository. The API has a public demonstration page and health endpoint. The autoscaler has a private status endpoint and starts in observe/dry-run mode. Shared measurement authentication and service references are configured by the template.

After deployment, create an environment-scoped Railway project token and add it to the autoscaler as `RAILWAY_API_TOKEN`. Enable scaling only after checking the target and policy. No account token, database, or volume is required.

## Why Deploy a Python Autoscaler on Railway?

Use Railway's automatic vertical resource scaling together with an application-specific horizontal controller. Inspect resource usage, generate a bounded workload, observe real replica identities, and return toward baseline after demand subsides.

## Common Use Cases

- Learn the difference between vertical resource use and horizontal replica counts.
- Explore a sampled in-flight-request scaling policy for a stateless HTTP service.
- Adapt the policy to an application's own load signal and availability requirements.

## Dependencies for a Python Autoscaler

Railway builds the repository's Dockerfile with Python 3.13. The application and controller use the standard library. The default policy is one to three API replicas and one controller, with a bounded replica policy. Set appropriate per-replica CPU and memory ceilings after deployment; the repository includes an example in its IaC file. Both services and additional replicas incur usage costs.

### Deployment Dependencies

- A Railway account and a plan that supports the required resources and replicas.
- An environment-scoped project token created after the template deployment and supplied to the controller.
- Python 3.11 or newer locally for the optional bounded request runner and tests.
- A stateless single-region workload, one active controller, and suitable alert/spending controls.

This template starts with sleeping disabled. Stop the example deployments when finished; choose production redundancy and operating controls for your own application.
