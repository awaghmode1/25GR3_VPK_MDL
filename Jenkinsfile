
pipeline {
  agent { label 'linux' } // Change to your Jenkins node/agent label

  options {
    timestamps()
    ansiColor('xterm')
    disableConcurrentBuilds()
  }

  environment {
    PYTHON_VERSION = '3.10'
    ARTIFACT_NAME  = 'Deployment Automation' // aligns with Azure pipeline
  }

  triggers {
    // If this is a Multibranch Pipeline job, webhooks are preferred and this block can be omitted.
    // pollSCM('H/5 * * * *')
  }

  stages {

    // ======================================
    // Stage 1: Build & Package  (package + publish)
    // ======================================
    stage('Build & Package') {
      when { branch 'main' } // mirrors Azure trigger on main
      steps {
        checkout scm

        sh '''
          set -euo pipefail
          # Use python3 if available; otherwise fallback to python
          if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi

          echo "Using $PY ($($PY -V || true))"

          # Create venv and install dependencies
          $PY -m venv .venv
          . .venv/bin/activate
          python -m pip install --upgrade pip
          pip install requests pandas

          # Package sources, excluding .venv/.git
          mkdir -p .package/project_root
          if command -v rsync >/dev/null 2>&1; then
            rsync -a --exclude='.venv' --exclude='.git' ./ ./.package/project_root/
          else
            echo "rsync not found; using tar fallback"
            tar --exclude='./.venv' --exclude='./.git' -cf - . | (cd .package/project_root && tar -xf -)
          fi

          echo "Package contents:"
          ls -la .package/project_root | head -n 50
        '''

        // Make the package available to later stages in the same run
        stash includes: '.package/**', name: 'pkg', useDefaultExcludes: false

        // Optional: keep a copy in Jenkins for auditing
        archiveArtifacts artifacts: '.package/**', fingerprint: true, onlyIfSuccessful: true
      }
    }

    // ======================================
    // Stage 2: Deploy to POC1
    // ======================================
    stage('Deploy to POC1') {
      when { branch 'main' }
      steps {
        unstash 'pkg'

        // Map Azure "DownloadSecureFile" → Jenkins Credentials (Secret file)
        // Create credentials with IDs: auth_json, payload_json, deployment_json
        withCredentials([
          file(credentialsId: 'auth_json',       variable: 'AUTH_JSON'),
          file(credentialsId: 'payload_json',    variable: 'PAYLOAD_JSON'),
          file(credentialsId: 'deployment_json', variable: 'DEPLOYMENT_JSON'),
          // For pushing back to repo via HTTPS (see Notes section)
          usernamePassword(credentialsId: 'git_push_creds', usernameVariable: 'GIT_USERNAME', passwordVariable: 'GIT_PASSWORD')
        ]) {
          sh '''
            set -euo pipefail
            cd ".package/project_root"

            # venv & deps
            if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
            $PY -m venv .venv
            . .venv/bin/activate
            python -m pip install --upgrade pip
            pip install requests pandas

            # Secure files → working dir
            cp "$AUTH_JSON"       authentication.json
            cp "$PAYLOAD_JSON"    payload.json
            cp "$DEPLOYMENT_JSON" deployment.json

            echo "Preparing input CSV..."
            REPO_CSV="$WORKSPACE/Deployment_Automation/GVault_Deployment_Steps.csv"
            ALT_CSV="$WORKSPACE/GVault_Deployment_Steps.csv"
            if [ ! -f "${REPO_CSV}" ] && [ -f "${ALT_CSV}" ]; then
              REPO_CSV="${ALT_CSV}"
            fi

            DEST_DIR="Deployment_Automation"
            mkdir -p "${DEST_DIR}"

            if [ ! -f "${REPO_CSV}" ]; then
              echo "ERROR: CSV not found at ${REPO_CSV}"
              echo "Checked out repo path: $WORKSPACE"
              ls -la "$WORKSPACE" || true
              exit 1
            fi

            cp -v "${REPO_CSV}" "${DEST_DIR}/GVault_Deployment_Steps.csv"
            echo "Directory tree (truncated):"
            ls -R . | head -n 200

            # Run Python deployment with ENVIRONMENT=POC1
            ENVIRONMENT=POC1 python Deployment_Automation/gvault_25gr2_deployment.py

            # Sync latest environment-named CSV back to repo checkout
            ENV_NAME="POC1"
            SRC_DIR="$PWD/Deployment_Automation"
            REPO_DIR="$WORKSPACE/Deployment_Automation"
            mkdir -p "${REPO_DIR}"

            LATEST_CSV="$(ls -1t "${SRC_DIR}/GVault_Deployment_Steps_${ENV_NAME}_"*.csv 2>/dev/null | head -n 1 || true)"
            if [ -z "${LATEST_CSV}" ]; then
              echo "ERROR: No environment-specific CSV found in ${SRC_DIR} for ENV=${ENV_NAME}"
              ls -la "${SRC_DIR}" || true
              exit 1
            fi

            STABLE_ENV="${REPO_DIR}/GVault_Deployment_Steps_${ENV_NAME}.csv"
            cp -f "${LATEST_CSV}" "${STABLE_ENV}"

            COMMON="${REPO_DIR}/GVault_Deployment_Steps.csv"
            cp -f "${STABLE_ENV}" "${COMMON}" || true

            echo "=== Preview top 25 lines ==="
            head -n 25 "${STABLE_ENV}" || true
            head -n 25 "${COMMON}"    || true

            # Commit & push CSV updates
            cd "$WORKSPACE"
            git --version
            git config --global --add safe.directory "$WORKSPACE"
            git config user.name  "jenkins"
            git config user.email "jenkins@local"

            git add Deployment_Automation/GVault_Deployment_Steps_${ENV_NAME}.csv
            git add Deployment_Automation/GVault_Deployment_Steps.csv || true

            if ! git diff --cached --quiet; then
              git commit -m "Pipeline: update deployment steps CSV (${ENV_NAME})"

              REPO_URL="$(git config --get remote.origin.url)"
              CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

              if echo "$REPO_URL" | grep -qE '^https?://'; then
                # embed credentials for push (masked by Jenkins)
                REPO_URL_AUTH="$(echo "$REPO_URL" | sed -E "s#https://#https://${GIT_USERNAME}:${GIT_PASSWORD}@#")"
                git push "$REPO_URL_AUTH" "HEAD:${CURRENT_BRANCH}"
              else
                # SSH-based remotes: requires Jenkins SSH Agent plugin & configured key
                git push origin "HEAD:${CURRENT_BRANCH}"
              fi
              echo "Pushed changes to ${CURRENT_BRANCH}"
            else
              echo "No changes to commit."
            fi
          '''
        }
      }
      post {
        always { echo 'POC1 stage finished (success or failure).' }
      }
    }

    // ======================================
    // Stage 3: Deploy to CONTIGENCY
    // (Keep the spelling consistent with your JSON/env keys)
    // ======================================
    stage('Deploy to CONTIGENCY') {
      when { branch 'main' }
      steps {
        unstash 'pkg'

        withCredentials([
          file(credentialsId: 'auth_json',       variable: 'AUTH_JSON'),
          file(credentialsId: 'payload_json',    variable: 'PAYLOAD_JSON'),
          file(credentialsId: 'deployment_json', variable: 'DEPLOYMENT_JSON'),
          usernamePassword(credentialsId: 'git_push_creds', usernameVariable: 'GIT_USERNAME', passwordVariable: 'GIT_PASSWORD')
        ]) {
          sh '''
            set -euo pipefail
            cd ".package/project_root"

            if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
            $PY -m venv .venv
            . .venv/bin/activate
            python -m pip install --upgrade pip
            pip install requests pandas

            cp "$AUTH_JSON"       authentication.json
            cp "$PAYLOAD_JSON"    payload.json
            cp "$DEPLOYMENT_JSON" deployment.json

            echo "Preparing input CSV (Contigency)..."
            REPO_CSV="$WORKSPACE/Deployment_Automation/GVault_Deployment_Steps_Contigency.csv"
            if [ ! -f "${REPO_CSV}" ]; then
              REPO_CSV="$WORKSPACE/Deployment_Automation/GVault_Deployment_Steps.csv"
            fi
            DEST_DIR="Deployment_Automation"
            mkdir -p "${DEST_DIR}"

            if [ ! -f "${REPO_CSV}" ]; then
              echo "ERROR: CSV not found at ${REPO_CSV}"
              ls -la "$WORKSPACE/Deployment_Automation" || true
              exit 1
            fi

            cp -v "${REPO_CSV}" "${DEST_DIR}/GVault_Deployment_Steps.csv"

            # Run Python deployment with ENVIRONMENT=Contigency
            ENVIRONMENT=Contigency python Deployment_Automation/gvault_25gr2_deployment.py

            ENV_NAME="Contigency"
            SRC_DIR="$PWD/Deployment_Automation"
            REPO_DIR="$WORKSPACE/Deployment_Automation"
            mkdir -p "${REPO_DIR}"

            LATEST_CSV="$(ls -1t "${SRC_DIR}/GVault_Deployment_Steps_${ENV_NAME}_"*.csv 2>/dev/null | head -n 1 || true)"
            if [ -z "${LATEST_CSV}" ]; then
              echo "ERROR: No environment-specific CSV found in ${SRC_DIR} for ENV=${ENV_NAME}"
              ls -la "${SRC_DIR}" || true
              exit 1
            fi

            STABLE_ENV="${REPO_DIR}/GVault_Deployment_Steps_${ENV_NAME}.csv"
            cp -f "${LATEST_CSV}" "${STABLE_ENV}"

            COMMON="${REPO_DIR}/GVault_Deployment_Steps.csv"
            cp -f "${STABLE_ENV}" "${COMMON}" || true

            echo "=== Preview top 25 lines ==="
            head -n 25 "${STABLE_ENV}" || true
            head -n 25 "${COMMON}"    || true

            # Commit & push CSV updates
            cd "$WORKSPACE"
            git --version
            git config --global --add safe.directory "$WORKSPACE"
            git config user.name  "jenkins"
            git config user.email "jenkins@local"

            git add Deployment_Automation/GVault_Deployment_Steps_${ENV_NAME}.csv
            git add Deployment_Automation/GVault_Deployment_Steps.csv || true

            if ! git diff --cached --quiet; then
              git commit -m "Pipeline: update deployment steps CSV (${ENV_NAME})"

              REPO_URL="$(git config --get remote.origin.url)"
              CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

              if echo "$REPO_URL" | grep -qE '^https?://'; then
                REPO_URL_AUTH="$(echo "$REPO_URL" | sed -E "s#https://#https://${GIT_USERNAME}:${GIT_PASSWORD}@#")"
                git push "$REPO_URL_AUTH" "HEAD:${CURRENT_BRANCH}"
              else
                git push origin "HEAD:${CURRENT_BRANCH}"
              fi
              echo "Pushed changes to ${CURRENT_BRANCH}"
            else
              echo "No changes to commit."
            fi
          '''
        }
      }
      post {
        always { echo 'CONTIGENCY stage finished (success or failure).' }
      }
    }
  }

  post {
    success { echo 'Pipeline completed successfully.' }
    failure { echo 'Pipeline failed.' }
    always  { cleanWs(deleteDirs: true, notFailBuild: true) }
  }
}
``
