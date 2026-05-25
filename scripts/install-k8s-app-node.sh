#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/versions.env" 2>/dev/null || true

DOCKER_VERSION="${DOCKER_VERSION:-5:29.5.2-1~ubuntu.24.04~noble}"
CONTAINERD_VERSION="${CONTAINERD_VERSION:-1.7.28-1~ubuntu.24.04~noble}"
KUBERNETES_VERSION="${KUBERNETES_VERSION:-1.36.0-1.1}"
KUBERNETES_MINOR="${KUBERNETES_MINOR:-v1.36}"
NODE_EXPORTER_VERSION="${NODE_EXPORTER_VERSION:-v1.10.2}"
CADVISOR_VERSION="${CADVISOR_VERSION:-0.54.1}"
FLANNEL_VERSION="${FLANNEL_VERSION:-v0.27.2}"

swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

cat >/etc/modules-load.d/k8s.conf <<'EOF'
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

cat >/etc/sysctl.d/k8s.conf <<'EOF'
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release apt-transport-https

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" > /etc/apt/sources.list.d/docker.list

curl -fsSL "https://pkgs.k8s.io/core:/stable:/${KUBERNETES_MINOR}/deb/Release.key" -o /etc/apt/keyrings/kubernetes-apt-keyring.asc
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.asc] https://pkgs.k8s.io/core:/stable:/${KUBERNETES_MINOR}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list

apt-get update
apt-get install -y \
  "containerd.io=${CONTAINERD_VERSION}" \
  "docker-ce=${DOCKER_VERSION}" \
  "docker-ce-cli=${DOCKER_VERSION}" \
  "kubelet=${KUBERNETES_VERSION}" \
  "kubeadm=${KUBERNETES_VERSION}" \
  "kubectl=${KUBERNETES_VERSION}"

containerd config default >/etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable --now docker kubelet
apt-mark hold containerd.io docker-ce docker-ce-cli kubelet kubeadm kubectl

kubeadm init --pod-network-cidr=10.244.0.0/16 --cri-socket unix:///run/containerd/containerd.sock
mkdir -p /home/ubuntu/.kube
cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
chown -R ubuntu:ubuntu /home/ubuntu/.kube
export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl apply -f "https://github.com/flannel-io/flannel/releases/download/${FLANNEL_VERSION}/kube-flannel.yml"

docker run -d --name node-exporter --restart unless-stopped --network host --pid host \
  -v /:/host:ro,rslave \
  "quay.io/prometheus/node-exporter:${NODE_EXPORTER_VERSION}" \
  --path.rootfs=/host

docker run -d --name cadvisor --restart unless-stopped \
  --volume=/:/rootfs:ro \
  --volume=/var/run:/var/run:ro \
  --volume=/sys:/sys:ro \
  --volume=/var/lib/docker/:/var/lib/docker:ro \
  --volume=/var/lib/containerd/:/var/lib/containerd:ro \
  --volume=/run/containerd/:/run/containerd:ro \
  --volume=/dev/disk/:/dev/disk:ro \
  --publish=8080:8080 \
  --privileged \
  --device=/dev/kmsg \
  "ghcr.io/google/cadvisor:${CADVISOR_VERSION}"
