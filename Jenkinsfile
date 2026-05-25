pipeline {
    agent any

    environment {
        APP_HOST = "3.7.236.240"
        APP_USER = "ubuntu"
        SSH_KEY = "/var/lib/jenkins/.ssh/xstream-devops-ap-south-1.pem"
        IMAGE_REPO = "docker.io/theraj71/xstream-backend"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Image') {
            steps {
                sh '''
                    SHORT_SHA="$(git rev-parse --short=7 HEAD)"
                    echo "${BUILD_NUMBER}-${SHORT_SHA}" > .image-tag
                    docker build -t "${IMAGE_REPO}:$(cat .image-tag)" .
                '''
            }
        }

        stage('Push Image') {
            steps {
                sh '''
                    docker push "${IMAGE_REPO}:$(cat .image-tag)"
                '''
            }
        }

        stage('Deploy to Kubernetes') {
            steps {
                sh '''
                    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${APP_USER}@${APP_HOST}" "
                        set -e
                        rm -rf /tmp/xstream-backend-k8s-${BUILD_NUMBER}
                        mkdir -p /tmp/xstream-backend-k8s-${BUILD_NUMBER}
                    "
                    scp -i "${SSH_KEY}" -o StrictHostKeyChecking=no k8s/deployment.yaml k8s/service.yaml "${APP_USER}@${APP_HOST}:/tmp/xstream-backend-k8s-${BUILD_NUMBER}/"
                    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${APP_USER}@${APP_HOST}" "
                        set -e
                        kubectl apply -f /tmp/xstream-backend-k8s-${BUILD_NUMBER}/service.yaml
                        kubectl apply -f /tmp/xstream-backend-k8s-${BUILD_NUMBER}/deployment.yaml
                        kubectl set image deployment/xstream-backend xstream-backend=${IMAGE_REPO}:$(cat .image-tag)
                        kubectl rollout status deployment/xstream-backend --timeout=180s
                        rm -rf /tmp/xstream-backend-k8s-${BUILD_NUMBER}
                    "
                '''
            }
        }
    }

    post {
        always {
            sh 'rm -f .image-tag'
        }
    }
}
