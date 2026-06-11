# Infra-Mind 
## Kubernetes | Claude AI | ArgoCD | HashiCorp Vault | External Secrets Operator 

> **Note:** This project is currently running on a local Kubernetes cluster for development and testing purposes — powered by Claude AI under the hood.

> *"Tired of reading kubectl logs at 2am. Built something to do it for me instead."*

---

## Table of Contents
1. [What It Does](#1-what-it-does)
2. [Sample Output](#2-sample-output)
3. [Architecture Overview](#3-architecture-overview)
4. [Technology Stack](#4-technology-stack)
5. [How Every Component Integrates](#5-how-every-component-integrates)
6. [Secrets Flow](#6-secrets-flow)
7. [GitOps Flow with ArgoCD](#7-gitops-flow-with-argocd)
8. [Repository Structure](#8-repository-structure)
9. [Setup and Installation](#9-setup-and-installation)
10. [Security Notes](#11-security-notes)

---

## 1. What It Does

Infra-Mind connects to your Kubernetes cluster, collects real-time pod states
and warning events, and sends them to Claude AI for intelligent triage,
returning a prioritised actionable incident report via a simple REST API.

---

## 2. Sample Output

**Request:**

```bash
sawandevrani@Sawan-Mac Infra-Mind % curl -s http://localhost:9090/summarize | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total Pods: {data[\"total_pods\"]}')
print(f'Warning Events: {data[\"warning_events\"]}')
print()
print(data['summary'])
"
```

**Response:**

```
Total Pods: 46
Warning Events: 9

# Kubernetes Cluster Analysis

## Executive Summary
The cluster is experiencing multiple critical failures preventing normal operations. While 0 pods are currently unhealthy, there are 4 distinct issues blocking deployments and infrastructure services, with image pull failures and missing infrastructure components being the primary blockers.

## Issues Ranked by Severity

### 1. **CRITICAL: Image Pull Failures (infra-mind deployment)**
- **Root Cause**: Docker image `infra-mind:v1.0.1` either doesn't exist in Docker Hub, is private, or requires authentication
- **Impact**: 2 deployment replicas stuck in ImagePullBackOff (9 and 65 backoff attempts)
- **Immediate Actions**:
  - Verify image exists: `docker pull docker.io/library/infra-mind:v1.0.1`
  - If private, create Docker registry secret and patch deployment with `imagePullSecrets`
  - Confirm correct image name/tag in deployment spec
  - Consider pushing to internal registry if not using Docker Hub

### 2. **CRITICAL: Missing StorageClass (Elasticsearch)**
- **Root Cause**: StorageClass `gp2` not provisioned in cluster
- **Impact**: Elasticsearch unable to provision persistent volumes (741 failed attempts)
- **Immediate Actions**:
  - Create missing StorageClass: `kubectl apply -f - <<EOF` with gp2 definition (or use your cloud provider's equivalent)
  - Or patch Elasticsearch to use existing StorageClass: `kubectl patch elasticsearch elasticsearch-master -p '{"spec":{"nodes":[{"config":{"node.store.allow_mmap":false}}]}}'`

### 3. **HIGH: Missing SecretStore (External Secrets)**
- **Root Cause**: SecretStore "vault-backend" referenced but not created in cluster
- **Impact**: anthropic-secret cannot sync, blocking dependent applications
- **Immediate Actions**:
  - Create SecretStore resource: `kubectl apply -f secretstore-vault-backend.yaml` in default namespace
  - Verify Vault connectivity and credentials are configured
  - Check External Secrets operator is running

### 4. **MEDIUM: ArgoCD ApplicationSet Controller Crash Loop**
- **Root Cause**: ApplicationSet controller repeatedly failing (331 restart attempts)
- **Impact**: ArgoCD cannot reconcile application sets
- **Immediate Actions**:
  - Check logs: `kubectl logs -n argocd argocd-applicationset-controller-cf6df4d44-xpdg9 --tail=100`
  - Verify ArgoCD RBAC permissions
  - Restart pod: `kubectl delete pod -n argocd argocd-applicationset-controller-cf6df4d44-xpdg9`
  - Check for resource constraints or missing CRDs

```

---

## 3. Architecture Overview

    +---------------------------------------------------------------+
    |                    Kubernetes Cluster                         |
    |                                                               |
    |   [vault namespace]            [argocd namespace]             |
    |   HashiCorp Vault              ArgoCD GitOps engine           |
    |   Raft storage                 Watches GitHub repo            |
    |        |                               |                      |
    |        | secrets                       | syncs manifests      |
    |        v                               v                      |
    |   [external-secrets ns]        [default namespace]            |
    |   External Secrets             +--------------------+         |
    |   Operator (ESO)  ---------->  | infra-mind pod     |         |
    |                                | Flask + Python     |         |
    |                                +--------+-----------+         |
    |                                         |                     |
    |                                         v                     |
    |                                Kubernetes API                 |
    |                                (pods + events)                |
    +---------------------------------------------------------------+
              ^                               |
              |                               v
    +------------------+           +--------------------+
    |   GitHub Repo    |           |   Anthropic API    |
    |  source of truth |           |  Claude AI triage  |
    +------------------+           +--------------------+

---

## 4. Technology Stack

| Component        | Technology                          | Purpose                               |
|------------------|-------------------------------------|---------------------------------------|
| Runtime          | Kubernetes                          | Manages all containers and resources  |
| Deployment       | ArgoCD (GitOps)                     | Continuously syncs Git repo to cluster|
| App Framework    | Python + Flask                      | REST API serving cluster triage       |
| Secrets Store    | HashiCorp Vault (Raft)              | Encrypted secrets with Shamir unseal  |
| Secrets Sync     | External Secrets Operator           | Bridges Vault to native K8s Secrets   |
| Image Registry   | Docker Hub with imagePullSecrets    | Stores and serves container images    |
| AI Model         | Anthropic Claude (claude-haiku-4-5) | Intelligent infrastructure triage     |
| Access Control   | Scoped ServiceAccount + ClusterRole | Least-privilege pod permissions       |

---

## 5. How Every Component Integrates

### Step 1: ArgoCD Watches GitHub

ArgoCD is the GitOps engine. It continuously polls the GitHub repository
and compares the desired state (Git) against the live state (cluster).
Any difference triggers an automatic sync with no manual kubectl apply needed.

    GitHub repo (desired state)
            |
            | ArgoCD polls every 3 minutes
            v
    ArgoCD application-controller
            |
            | kubectl apply -f k8s/
            v
    Kubernetes cluster (live state)

### Step 2: Vault Stores Secrets Encrypted at Rest

HashiCorp Vault runs as a StatefulSet with Raft storage on a persistent volume.
All secrets are encrypted using an encryption key protected by Shamir's Secret
Sharing, split into 3 key shards with 2 required to unseal.

Vault is SEALED on every restart. A human must provide 2 of the 3 unseal key
shards before Vault can serve any secrets. This ensures secrets cannot be
accessed without explicit authorisation even if the pod restarts unexpectedly.

### Step 3: External Secrets Operator Bridges Vault to Kubernetes

ESO is a Kubernetes operator that runs continuously in the cluster.
It reads two custom resources you define:

    SecretStore    ->  WHERE is Vault and what token to use for auth
    ExternalSecret ->  WHAT secret to fetch and what K8s Secret to create

ESO calls the Vault API on a schedule, pulls the secret value, and creates
or updates a native Kubernetes Secret object automatically.

    Vault API
        |
        | ESO fetches every 1h using scoped token
        v
    Kubernetes Secret "anthropic-secret"
        |
        | mounted as env var
        v
    infra-mind pod

 **Note:**

Vault no longer uses a manually created ESO token. Instead, External Secrets Operator authenticates to Vault using Kubernetes auth and a dedicated service account.

Create the Vault policy:

```bash
vault policy write infra-mind-policy - <<EOF
path "secret/data/infra-mind" {
  capabilities = ["read"]
}

path "secret/metadata/infra-mind" {
  capabilities = ["read", "list"]
}
EOF


### Step 4: infra-mind Pod Reads the Secret and Calls Claude

The Flask app reads ANTHROPIC_API_KEY from the environment.
It has no knowledge of Vault — it just reads a standard env var.

When /summarize is called:
1. App calls Kubernetes API using its ServiceAccount token (read-only RBAC)
2. Fetches all pods and warning events across all namespaces
3. Sends cluster state to Claude API with an SRE triage prompt
4. Returns structured JSON with severity-ranked issues and remediation steps

---

## 6. Secrets Flow

    Vault (encrypted at rest)
      |
      | Shamir unseal: 2 of 3 key shards required at startup
      v
    Vault KV v2 engine: secret/infra-mind
      | ANTHROPIC_API_KEY = sk-ant-...
      |
      | ESO polls every 1h using Kubernetes service account auth
      | Token policy: read only on secret/data/infra-mind
      v
    Kubernetes Secret: anthropic-secret
      |
      | Injected as environment variable into pod
      v
    infra-mind container
      | os.environ["ANTHROPIC_API_KEY"]
      v
    Anthropic Claude API

The application never interacts with Vault directly.
The scoped ESO Kubernetes service account cannot read any other secret path.
Each layer has access to only exactly what it needs.

---

## 7. GitOps Flow with ArgoCD

### Normal Deployment

    1. Edit k8s/deployment.yaml:
       image: sawandevrani/infra-mind:v1.0.1  ->  v1.0.2

    2. git add . && git commit -m "release: v1.0.2" && git push origin main

    3. ArgoCD detects change within ~3 minutes
       Desired (Git):  image v1.0.2
       Live (cluster): image v1.0.1
       DIFF DETECTED

    4. ArgoCD applies automatically (syncPolicy: automated)
       New pod spins up with v1.0.2, old pod terminates

    5. ArgoCD: Sync Status: Synced   Health Status: Healthy

    RULE: Never kubectl apply directly. Change Git. Let ArgoCD apply it.

### Self-Healing

    1. Someone accidentally deletes a resource:
       kubectl delete deployment infra-mind

    2. ArgoCD detects drift (selfHeal: true)

    3. ArgoCD re-creates the Deployment from Git within 30 seconds

---

## 8. Repository Structure

    infra-mind/
    |
    +-- app/
    |   +-- main.py                  Flask app + Kubernetes API + Claude integration
    |   +-- requirements.txt         Python dependencies
    |
    +-- Dockerfile                   Container image definition
    |
    +-- argocd-app.yaml              ArgoCD Application manifest (apply once manually)
    |
    +-- k8s/
    |   +-- serviceaccount.yaml      Scoped service account for pod identity
    |   +-- clusterrole.yaml         Read-only access to pods and events
    |   +-- clusterrolebinding.yaml  Binds ClusterRole to ServiceAccount
    |   +-- deployment.yaml          App deployment with imagePullSecrets
    |   +-- service.yaml             ClusterIP service on port 80
    |   +-- secretstore.yaml         ESO: defines connection to Vault
    |   +-- externalsecret.yaml      ESO: pulls ANTHROPIC_API_KEY from Vault


Every file in k8s/ is the DESIRED STATE of your cluster.
ArgoCD ensures the cluster ALWAYS matches this desired state.
To change anything: edit file, commit, push. Never kubectl apply directly.

---

## 9. Setup and Installation

### Prerequisites

- A running Kubernetes cluster
- Helm installed locally
- Anthropic API key from console.anthropic.com
- Docker Hub account

### Installation Order

| Step | What                          | Why It Must Come Here                               |
|------|-------------------------------|-----------------------------------------------------|
| 1    | Deploy HashiCorp Vault        | Must exist before ESO tries to connect              |
| 2    | Initialise and unseal Vault   | Vault is sealed on install, must unseal before use  |
| 3    | Store secret in Vault         | ESO needs the secret to exist before syncing        |
| 4    | Install External Secrets Operator | Must exist before SecretStore CRDs apply        |
| 5    | Install ArgoCD                | Infrastructure ready, now manage app from Git       |
| 6    | Apply ArgoCD Application      | Points ArgoCD at GitHub and triggers first sync     |

### Step 1: Deploy Vault

```
helm repo add hashicorp https://helm.releases.hashicorp.com

helm repo update

kubectl create namespace vault

helm install vault hashicorp/vault \
  --namespace vault \
  --set "server.dev.enabled=false" \
  --set "server.standalone.enabled=true" \
  --set "server.dataStorage.storageClass=hostpath" \
  --set "injector.enabled=false"
```

### Step 2: Initialise and Unseal Vault
```
kubectl exec -n vault -it vault-0 -- vault operator init \
  -key-shares=3 \
  -key-threshold=2 \
  -format=json > vault-init.json

kubectl exec -n vault vault-0 -- vault operator unseal KEY_1
kubectl exec -n vault vault-0 -- vault operator unseal KEY_2
```

### Step 3: Store Your API Key in Vault

```
vault policy write infra-mind-policy - <<EOF
path "secret/data/infra-mind" {
  capabilities = ["read"]
}
EOF

ESO_TOKEN=$(vault token create \
  -policy=infra-mind-policy \
  -ttl=8760h \
  -format=json | python3 -c "import sys,json; print(json.load(sys.stdin)['auth']['client_token'])")

kubectl create secret generic vault-eso-token \
  --namespace default \
  --from-literal=token=$ESO_TOKEN
```

### Step 4: Enable and configure Kubernetes auth

```
kubectl -n vault exec -it vault-0 -- sh

vault policy write infra-mind-policy - <<EOF
path "secret/data/infra-mind" {
  capabilities = ["read"]
}

path "secret/metadata/infra-mind" {
  capabilities = ["read", "list"]
}
EOF

Enable and configure Kubernetes auth:

vault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"

Create the Kubernetes auth role:

vault write auth/kubernetes/role/infra-mind-role \
  bound_service_account_names="infra-mind-vault-sa" \
  bound_service_account_namespaces="infra-mind" \
  policies="infra-mind-policy" \
  ttl="1h"

The application runtime uses `infra-mind-sa` in the `infra-mind` namespace.

The Vault authentication path uses a separate service account:`infra-mind-vault-sa` for External Secrets Operator and Vault access.

```

### Step 5: Install External Secrets Operator
```
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm install external-secrets \
  external-secrets/external-secrets \
  --namespace external-secrets \
  --create-namespace \
  --set installCRDs=true
```
### Step 6: Create Docker Hub Pull Secret
```
kubectl create secret docker-registry dockerhub-pull-secret \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_ACCESS_TOKEN \
  --docker-email=YOUR_EMAIL
```
### Step 7: Build and Push the Docker Image
```
docker build -t YOUR_USERNAME/infra-mind:v1.0.1 .
docker push YOUR_USERNAME/infra-mind:v1.0.1
```
### Step 8: Deploy via ArgoCD
```
kubectl apply -f argocd-app.yaml
```
### Step 9: Access the App
```
kubectl port-forward svc/infra-mind-svc 9090:80
```
### step 10: Health Check
```
Health Check : curl http://localhost:9090/health

Response: {"status": "ok"}
```

### Step 11. Verification Checks

#### ESO successfully synced from Vault
```
kubectl get externalsecret anthropic-secret
```
###### READY column should show: True

#### ArgoCD app is healthy
```
kubectl get application infra-mind -n argocd
```
###### SYNC STATUS: Synced  HEALTH STATUS: Healthy

#### Pod is running
```
kubectl get pods -l app=infra-mind
```
###### STATUS: Running 1/1

## 10. Security Notes
	•	Vault initialised with 3 key shares, threshold of 2 (Shamir’s Secret Sharing)
	•	Vault is sealed on every restart, secrets are inaccessible without explicit unseal
	•	ESO uses a scoped policy token, read access strictly limited to secret/infra-mind
	•	App ServiceAccount has read-only ClusterRole access to pods and events only