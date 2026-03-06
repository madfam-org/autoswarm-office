# Enclii Deployment API

## Overview
Enclii handles deployment and infrastructure management for the MADFAM ecosystem.

## Configuration
The `.enclii.yml` file at the repository root defines all services:
- nexus-api (port 4300)
- office-ui (port 4301)
- colyseus (port 4303)

## Deployment Process
1. CI builds Docker images (via `deploy-enclii.yml` GitHub Actions).
2. Images are pushed to the container registry.
3. Enclii is notified of the new images.
4. Rolling deployment with health checks.

## Key Endpoints
- `POST /deploy/trigger` — Trigger deployment for a service
- `GET /deploy/status/{id}` — Check deployment status
- `GET /deploy/history` — Deployment history

## Ports
- 4200: Enclii API
- 4201: Enclii dashboard
- 4202-4204: Reserved

## Best Practices
- Never deploy manually — always use the CI/CD pipeline.
- Monitor deployment status after triggering.
- Rollback using Enclii if health checks fail.
