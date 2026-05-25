pipeline {
    agent any

    environment {
        APP_HOST = "3.7.236.240"
        APP_USER = "ubuntu"
        SSH_KEY = "/var/lib/jenkins/.ssh/xstream-devops-ap-south-1.pem"
        REMOTE_DIR = "/tmp/xstream-backend-build"
        IMAGE_NAME = "xstream-backend:local"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Package Source') {
            steps {
                sh '''
                    rm -f /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz
                    tar \
                      --exclude=.git \
                      --exclude=.terraform \
                      --exclude='*.tfstate*' \
                      --exclude='*.tfvars' \
                      --exclude='*.pem' \
                      -czf /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz .
                '''
            }
        }

        stage('Build and Deploy on App Node') {
            steps {
                sh '''
                    scp -i "${SSH_KEY}" -o StrictHostKeyChecking=no /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz "${APP_USER}@${APP_HOST}:/tmp/xstream-backend-${BUILD_NUMBER}.tar.gz"
                    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "${APP_USER}@${APP_HOST}" "
                        set -e
                        rm -rf ${REMOTE_DIR}
                        mkdir -p ${REMOTE_DIR}
                        tar -xzf /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz -C ${REMOTE_DIR}
                        cd ${REMOTE_DIR}
                        sudo docker build -t ${IMAGE_NAME} .
                        sudo docker save ${IMAGE_NAME} | sudo ctr -n k8s.io images import -
                        kubectl apply -f k8s/service.yaml
                        kubectl apply -f k8s/deployment.yaml
                        kubectl rollout restart deployment/xstream-backend
                        kubectl rollout status deployment/xstream-backend --timeout=180s
                        rm -rf ${REMOTE_DIR} /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz
                    "
                '''
            }
        }
    }

    post {
        always {
            sh 'rm -f /tmp/xstream-backend-${BUILD_NUMBER}.tar.gz'
        }
    }
}
