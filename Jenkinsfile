pipeline {
    agent any

    environment {
        DOCKER_IMAGE = "xstream-backend"
        DOCKER_REGISTRY = "your-dockerhub-username"
        IMAGE_TAG = "${env.BUILD_NUMBER}"
        KUBECONFIG_CREDENTIAL = "k8s-kubeconfig" // Jenkins credential ID for Kubernetes cluster
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    dockerImage = docker.build("${DOCKER_REGISTRY}/${DOCKER_IMAGE}:${IMAGE_TAG}")
                    docker.build("${DOCKER_REGISTRY}/${DOCKER_IMAGE}:latest")
                }
            }
        }

        stage('Push to Docker Registry') {
            steps {
                script {
                    withDockerRegistry(credentialsId: 'dockerhub-credentials', url: '') {
                        dockerImage.push()
                        dockerImage.push("latest")
                    }
                }
            }
        }

        stage('Deploy to Kubernetes') {
            steps {
                withCredentials([file(credentialsId: "${KUBECONFIG_CREDENTIAL}", variable: 'KUBECONFIG')]) {
                    sh '''
                        # Replace image tag in deployment file
                        sed -i "s|image: .*|image: ${DOCKER_REGISTRY}/${DOCKER_IMAGE}:${IMAGE_TAG}|g" k8s/deployment.yaml
                        
                        # Apply Kubernetes manifests
                        kubectl apply -f k8s/deployment.yaml
                        kubectl apply -f k8s/service.yaml
                    '''
                }
            }
        }
    }
}