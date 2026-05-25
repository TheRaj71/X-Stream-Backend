terraform {
  required_version = "= 1.15.4"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.46.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region for the EC2 deployment."
  type        = string
  default     = "us-east-1"
}

variable "key_name" {
  description = "Existing AWS EC2 key pair name for SSH."
  type        = string
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH into the instances. Use your public IP /32."
  type        = string
}

variable "public_web_cidr" {
  description = "CIDR allowed to access app, Jenkins, Prometheus, and Grafana."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ubuntu_ami_id" {
  description = "Pinned Ubuntu Server AMI ID. Leave empty to use Canonical Ubuntu 24.04 LTS lookup for the selected region."
  type        = string
  default     = ""
}

variable "jenkins_instance_type" {
  type    = string
  default = "t3.small"
}

variable "app_instance_type" {
  type    = string
  default = "t3.small"
}

variable "monitoring_instance_type" {
  type    = string
  default = "t3.micro"
}

data "aws_ami" "ubuntu_2404" {
  count       = var.ubuntu_ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  ami_id = var.ubuntu_ami_id != "" ? var.ubuntu_ami_id : data.aws_ami.ubuntu_2404[0].id

  common_tags = {
    Project   = "xstream"
    ManagedBy = "terraform"
    Branch    = "aws"
  }
}

resource "aws_security_group" "jenkins" {
  name        = "xstream-jenkins-sg"
  description = "Jenkins and Terraform host"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "Jenkins"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.public_web_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "xstream-jenkins-sg" })
}

resource "aws_security_group" "app" {
  name        = "xstream-app-sg"
  description = "Single-node Kubernetes app host"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "Frontend NodePort"
    from_port   = 30081
    to_port     = 30081
    protocol    = "tcp"
    cidr_blocks = [var.public_web_cidr]
  }

  ingress {
    description = "Backend NodePort"
    from_port   = 30080
    to_port     = 30080
    protocol    = "tcp"
    cidr_blocks = [var.public_web_cidr]
  }

  ingress {
    description     = "Node exporter from monitoring"
    from_port       = 9100
    to_port         = 9100
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring.id]
  }

  ingress {
    description     = "cAdvisor from monitoring"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "xstream-app-sg" })
}

resource "aws_security_group" "monitoring" {
  name        = "xstream-monitoring-sg"
  description = "Prometheus and Grafana host"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "Prometheus"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = [var.public_web_cidr]
  }

  ingress {
    description = "Grafana"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = [var.public_web_cidr]
  }

  ingress {
    description = "Node exporter from monitoring host"
    from_port   = 9100
    to_port     = 9100
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "xstream-monitoring-sg" })
}

resource "aws_instance" "jenkins" {
  ami                    = local.ami_id
  instance_type          = var.jenkins_instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.jenkins.id]
  user_data_base64       = filebase64("${path.module}/../scripts/install-jenkins-terraform.sh")

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = merge(local.common_tags, { Name = "xstream-ec2-1-jenkins-terraform" })
}

resource "aws_instance" "app" {
  ami                    = local.ami_id
  instance_type          = var.app_instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.app.id]
  user_data_base64       = filebase64("${path.module}/../scripts/install-k8s-app-node.sh")

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = merge(local.common_tags, { Name = "xstream-ec2-2-kubernetes-app" })
}

resource "aws_instance" "monitoring" {
  ami                    = local.ami_id
  instance_type          = var.monitoring_instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.monitoring.id]
  user_data = templatefile("${path.module}/../scripts/install-monitoring.sh.tftpl", {
    app_private_ip = aws_instance.app.private_ip
  })

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = merge(local.common_tags, { Name = "xstream-ec2-3-monitoring" })
}

resource "aws_eip" "jenkins" {
  domain   = "vpc"
  instance = aws_instance.jenkins.id

  tags = merge(local.common_tags, { Name = "xstream-jenkins-eip" })
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id

  tags = merge(local.common_tags, { Name = "xstream-app-eip" })
}

resource "aws_eip" "monitoring" {
  domain   = "vpc"
  instance = aws_instance.monitoring.id

  tags = merge(local.common_tags, { Name = "xstream-monitoring-eip" })
}

output "jenkins_public_ip" {
  value = aws_eip.jenkins.public_ip
}

output "app_public_ip" {
  value = aws_eip.app.public_ip
}

output "monitoring_public_ip" {
  value = aws_eip.monitoring.public_ip
}

output "frontend_url" {
  value = "http://${aws_eip.app.public_ip}:30081"
}

output "backend_url" {
  value = "http://${aws_eip.app.public_ip}:30080"
}

output "jenkins_url" {
  value = "http://${aws_eip.jenkins.public_ip}:8080"
}

output "grafana_url" {
  value = "http://${aws_eip.monitoring.public_ip}:3000"
}

output "prometheus_url" {
  value = "http://${aws_eip.monitoring.public_ip}:9090"
}
