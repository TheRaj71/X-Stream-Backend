# X-Stream AWS EC2 DevOps Deployment

This branch is prepared for a three-instance AWS EC2 deployment using Docker, kubeadm Kubernetes, Jenkins, Prometheus, Grafana, and Terraform.

## Architecture

| Instance | Purpose | Instance type | Main ports |
| --- | --- | --- | --- |
| EC2-1 | Jenkins, Terraform CLI, Docker builds | `t3.small` | `22`, `8080` |
| EC2-2 | Single-node Kubernetes app runtime, backend, frontend, node exporter, cAdvisor | `t3.small` | `22`, `30080`, `30081`, internal `9100`, internal `8080` |
| EC2-3 | Prometheus, Grafana, node exporter | `t3.micro` | `22`, `9090`, `3000` |

The Kubernetes services use `NodePort` because this is self-managed Kubernetes on EC2, not EKS with an AWS load balancer controller.

## Pinned Tool Versions

Pins are kept in `scripts/versions.env` and repeated in Terraform/bootstrap where cloud-init cannot source repository files.

| Tool | Version |
| --- | --- |
| Terraform | `1.15.4` |
| AWS provider | `6.46.0` |
| Docker Engine | `29.5.2` apt package `5:29.5.2-1~ubuntu.24.04~noble` |
| containerd | `1.7.28-1~ubuntu.24.04~noble` |
| Kubernetes | `1.36.0-1.1` from `pkgs.k8s.io/core:/stable:/v1.36` |
| Jenkins LTS | `2.541.3` |
| Prometheus | `v3.5.3` LTS |
| Grafana | `13.0.1-security-01` |
| node-exporter | `v1.10.2` |
| cAdvisor | `0.54.1` |
| Flannel | `v0.27.2` |

## What You Need Before Deployment

- AWS account with billing enabled.
- AWS CLI configured locally with a limited IAM user or role. Do not use root credentials.
- Existing EC2 key pair in the selected AWS region.
- Your public IP in CIDR format, for example `203.0.113.10/32`.
- Jenkins EC2 access to the app node SSH key at `/var/lib/jenkins/.ssh/xstream-devops-ap-south-1.pem`.
- Jenkins Docker login configured for `theraj71`.
- Kubernetes DockerHub pull secret named `dockerhub-pull-secret`.
- Frontend build environment file at `/var/lib/jenkins/xstream/frontend.env`.
- Backend secret values. Start from `k8s/backend-secret.example.yaml`, replace values, and apply it before backend deployment.

DockerHub images are tagged as `BUILD_NUMBER-GIT_SHA`; the pipeline does not publish or deploy `latest`.

## Provision AWS Infrastructure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region      = "us-east-1"
key_name        = "your-existing-keypair"
ssh_cidr        = "your-public-ip/32"
public_web_cidr = "0.0.0.0/0"
```

Then run:

```bash
terraform init
terraform plan
terraform apply
```

Terraform outputs URLs for Jenkins, frontend, backend, Prometheus, and Grafana.

## Prepare Kubernetes Secret

SSH into EC2-2 and create the backend secret:

```bash
scp -i your-key.pem k8s/backend-secret.example.yaml ubuntu@APP_PUBLIC_IP:/home/ubuntu/backend-secret.yaml
ssh -i your-key.pem ubuntu@APP_PUBLIC_IP
nano backend-secret.yaml
kubectl apply -f backend-secret.yaml
```

## Jenkins Pipeline

Create two Jenkins pipeline jobs, one for backend and one for frontend, both tracking the `aws` branch.

Each Jenkinsfile:

- Polls the GitHub `aws` branch every two minutes.
- Builds with pinned Docker base images.
- Pushes a versioned image to DockerHub.
- Applies Kubernetes manifests.
- Updates the deployment to the exact pushed image tag.
- Waits for rollout completion.

## Access

- Frontend: `http://APP_PUBLIC_IP:30081`
- Backend: `http://APP_PUBLIC_IP:30080`
- Jenkins: `http://JENKINS_PUBLIC_IP:8080`
- Prometheus: `http://MONITORING_PUBLIC_IP:9090`
- Grafana: `http://MONITORING_PUBLIC_IP:3000`

Grafana bootstrap password is `change-me-after-first-login`; change it immediately.

## Recommended Improvements Before Production

- Replace public app NodePorts with an Nginx reverse proxy or AWS ALB.
- Restrict `public_web_cidr` instead of leaving it as `0.0.0.0/0`.
- Move Terraform state to an encrypted S3 backend with DynamoDB locking.
- Use ECR instead of Docker Hub if you want AWS-native image access control.
- Add TLS using Route 53 plus ACM/ALB, or Nginx plus Certbot.
- Add backup/retention policy for Grafana and Prometheus volumes.

## Official Docs Checked

- Docker Engine Ubuntu install docs: `https://docs.docker.com/engine/install/ubuntu/`
- Kubernetes kubeadm install docs: `https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/`
- Jenkins Linux install docs and LTS changelog: `https://www.jenkins.io/doc/book/installing/linux/`, `https://www.jenkins.io/changelog-stable/`
- Terraform install docs: `https://developer.hashicorp.com/terraform/install`
- Prometheus installation docs: `https://prometheus.io/docs/prometheus/latest/installation/`
- Grafana Docker install docs: `https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/`
