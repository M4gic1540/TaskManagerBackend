pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        SONAR_TOKEN = credentials('sonar-token')
        SONAR_HOST_URL = 'http://host.docker.internal:9000'
        SONAR_PROJECT_KEY = 'TaskManagerBackend'
        IMAGE_NAME = 'taskmanager-backend'
        // No hay .env en el checkout (está gitignored a propósito). Los
        // tests corren contra sqlite (ver IS_TESTING en settings.py) y no
        // tocan la DB real de GLPI, así que solo hace falta un SECRET_KEY
        // dummy para que Django arranque — no es un secreto real.
        SECRET_KEY = 'ci-dummy-secret-key-not-for-production'
    }

    stages {
        stage('Install dependencies') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --quiet --upgrade pip
                    pip install --quiet -r requirements.txt
                '''
            }
        }

        stage('Test + coverage') {
            steps {
                sh '''
                    . .venv/bin/activate
                    mkdir -p test-results
                    pytest accounts tickets inventory \
                        --junitxml=test-results/junit.xml \
                        --cov=. --cov-report=xml:coverage.xml --cov-report=term-missing
                '''
            }
            post {
                always {
                    // El plugin cobertura no es compatible con este core de
                    // Jenkins (NoClassDefFoundError: hudson.util.IOException2,
                    // clase legacy removida). coverage.xml igual queda
                    // publicado como artefacto del build más abajo.
                    junit 'test-results/junit.xml'
                }
            }
        }

        stage('SonarQube analysis') {
            steps {
                // Jenkins corre en un contenedor y usa el socket del host para
                // lanzar contenedores "hermanos" (docker-outside-of-docker):
                // un -v "$WORKSPACE:/usr/src" resolvería esa ruta contra el
                // filesystem del HOST, no el de Jenkins, y montaría vacío. Se
                // monta el volumen nombrado jenkins_home completo (mismo por
                // nombre en ambos contenedores) y se fija -w al workspace real,
                // así la ruta coincide sin depender de dónde vive el volumen.
                sh '''
                    docker run --rm \
                        -e SONAR_HOST_URL="${SONAR_HOST_URL}" \
                        -e SONAR_TOKEN="${SONAR_TOKEN}" \
                        -v jenkins_home:/var/jenkins_home \
                        -w "${WORKSPACE}" \
                        sonarsource/sonar-scanner-cli
                '''
            }
        }

        stage('Quality Gate') {
            steps {
                sh '''
                    set -e
                    echo "Esperando a que SonarQube procese el análisis..."
                    for i in $(seq 1 30); do
                        STATUS=$(curl -s -u "${SONAR_TOKEN}:" \
                            "${SONAR_HOST_URL}/api/qualitygates/project_status?projectKey=${SONAR_PROJECT_KEY}" \
                            | python3 -c "import json,sys; print(json.load(sys.stdin)['projectStatus']['status'])")
                        echo "Quality Gate: ${STATUS}"
                        if [ "$STATUS" = "OK" ]; then
                            exit 0
                        fi
                        if [ "$STATUS" = "ERROR" ]; then
                            echo "Quality Gate falló — revisa ${SONAR_HOST_URL}/dashboard?id=${SONAR_PROJECT_KEY}"
                            exit 1
                        fi
                        sleep 5
                    done
                    echo "Timeout esperando el resultado del Quality Gate"
                    exit 1
                '''
            }
        }

        stage('Docker build') {
            steps {
                sh '''
                    docker build -t ${IMAGE_NAME}:${BUILD_NUMBER} -t ${IMAGE_NAME}:latest .
                '''
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'coverage.xml', allowEmptyArchive: true
            cleanWs()
        }
    }
}
