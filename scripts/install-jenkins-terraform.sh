#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/versions.env" 2>/dev/null || true

JENKINS_VERSION="${JENKINS_VERSION:-2.541.3}"
TERRAFORM_VERSION="${TERRAFORM_VERSION:-1.15.4-1}"
DOCKER_VERSION="${DOCKER_VERSION:-5:29.5.2-1~ubuntu.24.04~noble}"
CONTAINERD_VERSION="${CONTAINERD_VERSION:-1.7.28-1~ubuntu.24.04~noble}"
DOCKER_COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-v2.40.3}"
KUBERNETES_VERSION="${KUBERNETES_VERSION:-1.36.0-1.1}"
KUBERNETES_MINOR="${KUBERNETES_MINOR:-v1.36}"

apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release git unzip openjdk-21-jre

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" > /etc/apt/sources.list.d/docker.list

curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key -o /etc/apt/keyrings/jenkins-keyring.asc
echo "deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" > /etc/apt/sources.list.d/jenkins.list

curl -fsSL https://apt.releases.hashicorp.com/gpg -o /etc/apt/keyrings/hashicorp.asc
echo "deb [signed-by=/etc/apt/keyrings/hashicorp.asc] https://apt.releases.hashicorp.com $(lsb_release -cs) main" > /etc/apt/sources.list.d/hashicorp.list

curl -fsSL "https://pkgs.k8s.io/core:/stable:/${KUBERNETES_MINOR}/deb/Release.key" -o /etc/apt/keyrings/kubernetes-apt-keyring.asc
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.asc] https://pkgs.k8s.io/core:/stable:/${KUBERNETES_MINOR}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list

apt-get update
apt-get install -y \
  "containerd.io=${CONTAINERD_VERSION}" \
  "docker-ce=${DOCKER_VERSION}" \
  "docker-ce-cli=${DOCKER_VERSION}" \
  jenkins="${JENKINS_VERSION}" \
  terraform="${TERRAFORM_VERSION}" \
  "kubectl=${KUBERNETES_VERSION}"

curl -fsSL "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

usermod -aG docker ubuntu || true
usermod -aG docker jenkins || true
systemctl enable --now docker jenkins
apt-mark hold containerd.io docker-ce docker-ce-cli jenkins terraform kubectl
