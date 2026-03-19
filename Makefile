PYTHON ?= python
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest

.PHONY: install test test-cov lint format \
        run-api run-api-ce run-api-ee \
        run-docker run-docker-ce run-docker-ee \
        edition-info clean \
        helm-lint helm-template helm-install-dev helm-install-prod helm-batch-10k

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .[dev]

test:
	$(PYTEST) ironcore/tests tests -v

test-ce:
	IRONCORE_EDITION=community $(PYTEST) ironcore/tests tests -v

test-ee:
	IRONCORE_EDITION=enterprise $(PYTEST) ironcore/tests tests -v

test-cov:
	$(PYTEST) ironcore/tests tests --cov=ironcore --cov=deployment --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check ironcore deployment tests
	$(PYTHON) -m mypy ironcore deployment

format:
	$(PYTHON) -m ruff format ironcore deployment tests

# ── Community Edition ─────────────────────────────────────────
run-api-ce:
	IRONCORE_EDITION=community \
	uvicorn ironcore.api.server:app --host 0.0.0.0 --port 8000 --reload

run-docker-ce:
	IRONCORE_EDITION=community docker compose up --build

# ── Enterprise Edition ────────────────────────────────────────
run-api-ee:
	IRONCORE_EDITION=enterprise \
	uvicorn ironcore.api.server:app --host 0.0.0.0 --port 8000 --reload

run-docker-ee:
	IRONCORE_EDITION=enterprise docker compose up --build

# ── Shortcuts (default = CE per .env.example) ─────────────────
run-api:
	uvicorn ironcore.api.server:app --host 0.0.0.0 --port 8000 --reload

run-docker:
	docker compose up --build

# ── Edition info ──────────────────────────────────────────────
edition-info:
	$(PYTHON) -c "from ironcore.edition import get_feature_list; import json; print(json.dumps(get_feature_list(), indent=2))"


clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info

# ── Kubernetes / Helm ─────────────────────────────────────────
helm-lint:
	helm lint charts/ironcore

helm-template:
	helm template ironcore charts/ironcore --debug

helm-install-dev:
	helm upgrade --install ironcore charts/ironcore \
	  --namespace ironcore-dev --create-namespace \
	  --set edition.value=enterprise \
	  --set replicaCount=1

helm-install-prod:
	helm upgrade --install ironcore charts/ironcore \
	  --namespace ironcore-prod --create-namespace \
	  -f charts/ironcore/values-prod.yaml

helm-batch-10k:
	helm upgrade --install ironcore-batch charts/ironcore \
	  --namespace ironcore-batch --create-namespace \
	  --set worker.batchMode=true \
	  --set keda.enabled=true \
	  --set keda.maxReplicaCount=10000 \
	  --set replicaCount=0
