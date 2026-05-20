provider "aws" {
  region = "us-east-1"
}

variable "key_name" {
  description = "Name of the SSH key pair"
  type        = string
  default     = "devops-key"
}

resource "aws_security_group" "devops_sg" {
  name        = "xstream-devops-sg"
  description = "Security group for Devops Class Project"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Jenkins"
  }

  ingress {
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Prometheus"
  }

  ingress {
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Grafana"
  }
  
  # Kubernetes NodePorts if needed
  ingress {
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "devops_server" {
  ami           = "ami-0c7217cdde317cfec" # Ubuntu 22.04 LTS (Update based on region/time)
  instance_type = "t3.large"
  key_name      = var.key_name
  
  vpc_security_group_ids = [aws_security_group.devops_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              # Update and install dependencies
              apt-get update -y
              apt-get install -y docker.io docker-compose git curl wget unzip htop
              
              systemctl start docker
              systemctl enable docker
              usermod -aG docker ubuntu
              
              # Install Jenkins
              wget -q -O - https://pkg.jenkins.io/debian/jenkins.io.key | apt-key add -
              sh -c 'echo deb http://pkg.jenkins.io/debian-stable binary/ > /etc/apt/sources.list.d/jenkins.list'
              apt-get update -y
              apt-get install -y openjdk-11-jre jenkins
              systemctl start jenkins
              systemctl enable jenkins
              
              # Install kubectl
              curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
              install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
              
              # Install Minikube
              curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
              install minikube-linux-amd64 /usr/local/bin/minikube
              
              sudo -u ubuntu -i minikube start --driver=docker
              EOF

  tags = {
    Name = "X-Stream-DevOps-Server"
  }
}

output "public_ip" {
  value = aws_instance.devops_server.public_ip
}