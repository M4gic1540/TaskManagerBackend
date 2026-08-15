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
        DOCKERHUB_REPO = 'm4gic/gestorinventario'
        DOCKERHUB_CREDENTIALS_ID = 'dockerhub-credentials'
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
                // Código como config/service_settings/*.py o gateway/ solo
                // se ejecuta bajo el DJANGO_SETTINGS_MODULE de su propio
                // microservicio (ver pytest.ini), nunca bajo config.settings
                // — un único coverage.xml del monolito los reportaría 0%
                // aunque estén testeados. Cada corrida escribe su propio
                // .coverage.<nombre> y se combinan al final en un solo
                // reporte antes de subirlo a SonarQube.
                sh '''
                    . .venv/bin/activate
                    mkdir -p test-results
                    COVERAGE_FILE=.coverage.monolito pytest accounts tickets inventory core \
                        --junitxml=test-results/junit.xml \
                        --cov=. --cov-report=
                    for svc in accounts tickets inventory gateway; do
                        COVERAGE_FILE=.coverage.$svc pytest --ds=config.service_settings.$svc $svc/ \
                            --junitxml=test-results/junit-$svc.xml \
                            --cov=. --cov-report=
                    done
                    coverage combine .coverage.monolito .coverage.accounts .coverage.tickets .coverage.inventory .coverage.gateway
                    coverage xml -o coverage.xml
                    coverage report
                '''
            }
            post {
                always {
                    // El plugin cobertura no es compatible con este core de
                    // Jenkins (NoClassDefFoundError: hudson.util.IOException2,
                    // clase legacy removida). coverage.xml igual queda
                    // publicado como artefacto del build más abajo.
                    junit 'test-results/junit*.xml'
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
                // sonar.working.directory: el scanner por defecto escribe
                // .scannerwork (incluye report-task.txt, que el siguiente
                // stage necesita para saber qué análisis esperar) en /tmp
                // DENTRO del contenedor efímero del scanner — se pierde al
                // salir. Se fuerza a que quede dentro del workspace montado.
                sh '''
                    docker run --rm \
                        -e SONAR_HOST_URL="${SONAR_HOST_URL}" \
                        -e SONAR_TOKEN="${SONAR_TOKEN}" \
                        -v jenkins_home:/var/jenkins_home \
                        -w "${WORKSPACE}" \
                        sonarsource/sonar-scanner-cli \
                        -Dsonar.working.directory="${WORKSPACE}/.scannerwork"
                '''
            }
        }

        stage('Quality Gate') {
            steps {
                // project_status?projectKey=... devuelve el resultado del
                // último análisis YA PROCESADO — si se consulta apenas se
                // sube el reporte, puede devolver el estado del scan
                // ANTERIOR (condición de carrera) en vez de esperar. Se
                // engancha al Compute Engine task de ESTE scan (su id queda
                // en .scannerwork/report-task.txt) y solo se consulta el
                // gate una vez que ese task específico terminó.
                sh '''
                    set -e
                    TASK_ID=$(grep ceTaskId .scannerwork/report-task.txt | cut -d= -f2)
                    echo "Esperando el Compute Engine task ${TASK_ID}..."
                    for i in $(seq 1 30); do
                        CE_STATUS=$(curl -s -u "${SONAR_TOKEN}:" "${SONAR_HOST_URL}/api/ce/task?id=${TASK_ID}" \
                            | python3 -c "import json,sys; print(json.load(sys.stdin)['task']['status'])")
                        echo "CE task: ${CE_STATUS}"
                        if [ "$CE_STATUS" = "SUCCESS" ]; then
                            break
                        fi
                        if [ "$CE_STATUS" = "FAILED" ] || [ "$CE_STATUS" = "CANCELED" ]; then
                            echo "El análisis en SonarQube falló (CE task ${CE_STATUS})"
                            exit 1
                        fi
                        sleep 5
                    done

                    ANALYSIS_ID=$(curl -s -u "${SONAR_TOKEN}:" "${SONAR_HOST_URL}/api/ce/task?id=${TASK_ID}" \
                        | python3 -c "import json,sys; print(json.load(sys.stdin)['task']['analysisId'])")
                    GATE_STATUS=$(curl -s -u "${SONAR_TOKEN}:" \
                        "${SONAR_HOST_URL}/api/qualitygates/project_status?analysisId=${ANALYSIS_ID}" \
                        | python3 -c "import json,sys; print(json.load(sys.stdin)['projectStatus']['status'])")
                    echo "Quality Gate: ${GATE_STATUS}"
                    if [ "$GATE_STATUS" != "OK" ]; then
                        echo "Quality Gate falló — revisa ${SONAR_HOST_URL}/dashboard?id=${SONAR_PROJECT_KEY}"
                        exit 1
                    fi
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

        stage('Docker push') {
            // Solo produccion publica en DockerHub — el resto de las ramas
            // (feature, develop, etc.) comparten el mismo tag :latest del
            // repo, así que si cualquiera pusheara se pisarían entre sí.
            when {
                branch 'produccion'
            }
            steps {
                sh '''
                    docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${DOCKERHUB_REPO}:${BUILD_NUMBER}
                    docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${DOCKERHUB_REPO}:latest
                '''
                // El plugin de credenciales inyecta usuario/token como env vars
                // scoped a este bloque — nunca quedan en el log ni en el Jenkinsfile.
                withCredentials([usernamePassword(
                    credentialsId: "${DOCKERHUB_CREDENTIALS_ID}",
                    usernameVariable: 'DOCKERHUB_USER',
                    passwordVariable: 'DOCKERHUB_TOKEN'
                )]) {
                    sh '''
                        echo "${DOCKERHUB_TOKEN}" | docker login -u "${DOCKERHUB_USER}" --password-stdin
                        docker push ${DOCKERHUB_REPO}:${BUILD_NUMBER}
                        docker push ${DOCKERHUB_REPO}:latest
                        docker logout
                    '''
                }
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
