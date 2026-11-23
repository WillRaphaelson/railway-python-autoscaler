import { defineRailway, github, project, service, preserve } from 'railway/iac';

export default defineRailway(() => {
  const api = service('api', {
    source: github('WillRaphaelson/railway-python-autoscaler', { branch: 'main' }),
    build: { builder: 'DOCKERFILE', dockerfilePath: 'Dockerfile' },
    start: 'python api.py', healthcheck: '/health', replicas: 1,
    deploy: {
      region: 'us-east4-eqdc4a', sleepApplication: false, drainingSeconds: 10,
      limitOverride: { containers: { cpu: 1, memoryBytes: 268435456 } },
    },
    env: {
      METRICS_TOKEN: preserve(),
      AUTOSCALER_STATUS_URL: 'http://${{autoscaler.RAILWAY_PRIVATE_DOMAIN}}:8080/state',
      PORT: '8080',
    },
  });
  const autoscaler = service('autoscaler', {
    source: github('WillRaphaelson/railway-python-autoscaler', { branch: 'main' }),
    build: { builder: 'DOCKERFILE', dockerfilePath: 'Dockerfile' },
    start: 'python autoscaler.py', healthcheck: '/health', replicas: 1,
    deploy: {
      region: 'us-east4-eqdc4a', sleepApplication: false,
      limitOverride: { containers: { cpu: 0.25, memoryBytes: 134217728 } },
    },
    env: {
      METRICS_TOKEN: api.env.METRICS_TOKEN,
      TARGET_SERVICE_ID: api.env.RAILWAY_SERVICE_ID,
      TARGET_LOAD_URL: 'https://${{api.RAILWAY_PUBLIC_DOMAIN}}/_load',
      RAILWAY_API_TOKEN: preserve(),
      MIN_REPLICAS: '1', MAX_REPLICAS: '3', TARGET_INFLIGHT: '4',
      POLL_SECONDS: '5', SCALE_UP_WINDOW_SECONDS: '10',
      SCALE_DOWN_WINDOW_SECONDS: '60', COOLDOWN_SECONDS: '30',
      SCALING_ENABLED: 'false', DRY_RUN: 'true', PORT: '8080',
    },
  });
  return project('python-autoscaling-cost-guide', { resources: [api, autoscaler] });
});
