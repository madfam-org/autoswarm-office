# ArgoCD Integration for AutoSwarm Office

## Enclii App-of-Apps Pattern

This directory contains the ArgoCD configuration for AutoSwarm Office.
It is designed to integrate with the Enclii infrastructure repository's
App-of-Apps pattern.

## How It Works

1. The Enclii repo contains a root ArgoCD Application (the "App of Apps")
   that uses an ApplicationSet controller to discover and manage all
   madfam project applications.

2. The `config.json` in this directory is consumed by Enclii's
   ApplicationSet controller. The controller reads the project metadata
   (repo URL, path, target revision, destination) and generates a
   corresponding ArgoCD Application resource automatically.

3. The `application.yaml` is the standalone ArgoCD Application manifest
   for this project. It can be applied directly for bootstrapping or
   used as a reference. In the standard Enclii workflow, the
   ApplicationSet controller generates this resource from `config.json`.

## Integration Steps

1. Ensure the Enclii repo's root ApplicationSet is configured to scan
   for `config.json` files across madfam project repositories.

2. Verify that the ArgoCD project `autoswarm-office` exists in ArgoCD
   or is created by Enclii's project provisioning.

3. The ApplicationSet controller will pick up `config.json` and create
   the Application resource targeting `infra/k8s/production/`.

4. Sync policy is set to automated with prune and self-heal enabled,
   so any changes pushed to the `main` branch will be automatically
   applied to the cluster.

## Manual Bootstrap

If you need to bootstrap outside the Enclii pattern:

```bash
kubectl apply -f application.yaml
```

## Retry Policy

The application is configured with a retry limit of 5 attempts using
exponential backoff (5s initial, factor of 2, max 3m). This handles
transient failures during sync operations.
