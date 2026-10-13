SHELL := /bin/bash
PORT ?= 8080
RUNS ?= 10
WARMUPS ?= 2
ITERATIONS ?= 100000
TIMEOUT ?= 120
BUILDER ?= paketobuildpacks/builder-noble-java-tiny:latest
PACK_IMAGE ?= buildpacksio/pack:0.40.9
HELPER_IMAGE ?= python:3.13-slim
DOCKER_SOCKET ?= /var/run/docker.sock
PLATFORM ?=
REPORT_HOST_RESULTS := $(CURDIR)/results
export PORT BUILDER PACK_IMAGE HELPER_IMAGE DOCKER_SOCKET PLATFORM REPORT_HOST_RESULTS
EXAMPLE_DIR_01 := 01-spring-java-baseline
EXAMPLE_DIR_02 := 02-spring-aot
EXAMPLE_DIR_03 := 03-spring-jvm-aot-cache
EXAMPLE_DIR_04 := 04-spring-aot-graalvm-native
EXAMPLES := $(EXAMPLE_DIR_01) $(EXAMPLE_DIR_02) $(EXAMPLE_DIR_03) $(EXAMPLE_DIR_04)
EXAMPLE_TARGETS := status validate build test-app bench clean render-k8s
.DEFAULT_GOAL := help
.PHONY: help compare $(EXAMPLE_TARGETS)

help:
	@printf '%s\n' \
	  'make status       Check Docker, Compose and the containerized pack CLI' \
	  'make validate     Validate the selected Compose file' \
	  'make build        Build its application image with Paketo (runs Java tests)' \
	  'make test-app     Build, start, wait for readiness and check the HTTP API' \
	  'make bench        Measure fresh containers; print a table and save an HTML report' \
	  'make compare      Build all four images and compare them in one report' \
	  'make render-k8s   Print the selected Deployment and Service YAML' \
	  'make clean        Remove the selected Compose containers and network' \
	  '' \
	  'Omit EXAMPLE for fzf; or use EXAMPLE=01|02|03|04 or a full directory name.' \
	  'make help and make compare do not open the picker.' \
	  'Options: PORT=8080 RUNS=10 WARMUPS=2 ITERATIONS=100000 TIMEOUT=120' \
	  'Build options: BUILDER=... PACK_IMAGE=... HELPER_IMAGE=... PLATFORM=linux/amd64' \
	  'IMAGE=registry.example.com/catalog:tag overrides the selected image.'

compare:
	@for example in $(EXAMPLES); do $(MAKE) --no-print-directory build EXAMPLE="$$example" IMAGE="aot-buildpacks/$$example:local" || exit $$?; done
	@mkdir -p results
	docker compose -f examples/$(EXAMPLE_DIR_01)/compose.yaml --profile benchmark run --rm --no-deps benchmark --example all --network aot-buildpacks-$(EXAMPLE_DIR_01)_default --runs $(RUNS) --warmups $(WARMUPS) --iterations $(ITERATIONS) --timeout $(TIMEOUT)

ifeq ($(strip $(EXAMPLE)),)
REQUESTED_TARGETS := $(filter $(EXAMPLE_TARGETS),$(MAKECMDGOALS))
.PHONY: select-example
$(EXAMPLE_TARGETS): select-example
select-example:
	@selected=$$(sh scripts/select-example.sh '$(REQUESTED_TARGETS)' $(EXAMPLES)) || exit $$?; \
	  $(MAKE) --no-print-directory $(REQUESTED_TARGETS) EXAMPLE="$$selected"
else
EXAMPLE_DIR := $(if $(EXAMPLE_DIR_$(EXAMPLE)),$(EXAMPLE_DIR_$(EXAMPLE)),$(filter $(EXAMPLE),$(EXAMPLES)))
ifeq ($(EXAMPLE_DIR),)
$(error Unknown EXAMPLE '$(EXAMPLE)'; use 01 through 04 or a full example directory name)
endif
EXAMPLE_NUMBER := $(firstword $(subst -, ,$(EXAMPLE_DIR)))
IMAGE ?= aot-buildpacks/$(EXAMPLE_DIR):local
export IMAGE
COMPOSE := docker compose -f examples/$(EXAMPLE_DIR)/compose.yaml

status:
	docker version
	$(COMPOSE) version
	$(COMPOSE) --profile tools run --rm --no-deps pack version

validate:
	$(COMPOSE) config --quiet

build: validate
	@bash scripts/build.sh '$(EXAMPLE_DIR)' '$(IMAGE)'

test-app: build
	$(COMPOSE) up --detach app
	$(COMPOSE) --profile tools run --rm --no-deps client --example $(EXAMPLE_DIR) --display-url http://localhost:$(PORT) --iterations $(ITERATIONS) --timeout $(TIMEOUT)
	@printf '\nReady: http://localhost:%s/ready\nStop: make clean EXAMPLE=%s\n\n' '$(PORT)' '$(EXAMPLE_NUMBER)'

bench: build
	@mkdir -p results
	$(COMPOSE) --profile benchmark run --rm --no-deps benchmark --example $(EXAMPLE_DIR) --image '$(IMAGE)' --network aot-buildpacks-$(EXAMPLE_DIR)_default --runs $(RUNS) --warmups $(WARMUPS) --iterations $(ITERATIONS) --timeout $(TIMEOUT)

render-k8s:
	@python3 scripts/render_k8s.py '$(EXAMPLE_DIR)' '$(IMAGE)'

clean:
	$(COMPOSE) --profile '*' down --remove-orphans
endif
