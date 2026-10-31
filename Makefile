.PHONY: install test doctor demo eval serve lint
install:      ## create venv + install
	python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,github]"
test:         ## offline unit tests (no API, no docker)
	pytest -q
lint:
	ruff check repro tests
doctor:       ## check API key, tool calling, docker
	repro doctor
pull:         ## pull the ARVO images listed in config/targets.yaml
	python scripts/pull_images.py
demo:         ## the two demo reports
	repro triage datasets/demo/slop_curl_01 --no-patch && repro triage datasets/demo/real_01
eval:
	repro eval datasets --no-patch
serve:
	repro serve
examples:     ## regenerate synthetic example runs (dashboard work without Docker)
	python scripts/make_example_runs.py
spend:        ## API spend across runs/
	repro spend
curl-image:   ## build the curl ASan/UBSan image (takes ~5-10 min)
	docker build -f docker/curl-asan.Dockerfile -t repro/curl-asan:latest .
