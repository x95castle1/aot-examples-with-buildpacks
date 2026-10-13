# Java AOT examples with buildpacks

Four independent Gradle projects run the same Spring Boot HTTP catalog using images produced by Cloud Native Buildpacks. This project owns its source, wrappers, buildpack settings, Compose files, Kubernetes manifests and benchmark harness. It has no build or runtime dependency on `aot-examples`, and no application Dockerfiles.

Each application loads eight products from a bundled CSV, looks up products, calculates quotes with a 10% discount at a subtotal of 20,000 cents, and runs a deterministic CPU computation. Two keyboards and one mouse produce subtotal 22,300 cents, discount 2,230 cents and total 20,070 cents. All four expose `/ready`, `/products/1`, `/quotes`, `/compute?iterations=100000` and `/native-metadata`. The last endpoint verifies bundled resources and reflective access to a discount policy. No database or external service is required.

| Example | Spring AOT | JVM AOT cache | Runtime |
| --- | --- | --- | --- |
| [01-spring-java-baseline](examples/01-spring-java-baseline/README.md) | Off | Off | Ordinary JVM |
| [02-spring-aot](examples/02-spring-aot/README.md) | On | Off | JVM with generated Spring initialization |
| [03-spring-jvm-aot-cache](examples/03-spring-jvm-aot-cache/README.md) | Off | On | JVM with a cache trained by Paketo |
| [04-spring-aot-graalvm-native](examples/04-spring-aot-graalvm-native/README.md) | On | Not applicable | Native executable |

Spring AOT generates initialization code and native metadata during the Gradle build. The JVM AOT cache reuses class-loading/linking work and training profiles while retaining HotSpot/JIT compilation. Native Image compiles reachable Java code into an executable with an included runtime. Native executables do not consume HotSpot AOT caches. These four examples demonstrate the separate buildpack options; there is no combined Spring AOT + JVM cache example here.

## Build and test the applications

Run commands from this repository root. Requirements: Docker with Compose v2, Make and Python 3.11 or later; fzf is optional when `EXAMPLE` is supplied. Docker supplies the pinned `pack` CLI and the HTTP/benchmark clients; Paketo supplies Java, Gradle's build-time JDK and the native compiler. No host Java, Gradle or pack installation is needed. Allow at least 8 GiB of available Docker memory for the native build.

```sh
make help
make build EXAMPLE=01
make test-app EXAMPLE=01
make clean EXAMPLE=01

make test-app EXAMPLE=02 PORT=8082
make clean EXAMPLE=02
make test-app EXAMPLE=03 PORT=8083
make clean EXAMPLE=03
make test-app EXAMPLE=04 PORT=8084
make clean EXAMPLE=04
```

`make build` runs `pack build` against the selected project's source and `buildpack.env`. Its Gradle arguments deliberately run `clean build`, including the Java workload, HTTP and runtime-hint tests. Gradle dependencies and buildpack layers can be cached, while these build arguments rerun the application tests. The native example performs Spring AOT during Gradle packaging; Paketo then invokes Native Image. Example 03 uses Paketo's context-refresh cache training, rather than the custom HTTP-workload training in the Dockerfile project.

`make test-app` builds the image, starts it through Compose, waits for a verified `/ready` response, prints curl commands and formatted JSON, and checks products, quotes, computation, metadata and invalid inputs. The service stays running. Stop an app before starting another on the same host port, or use `PORT` consistently. `ITERATIONS` controls the computation; `TIMEOUT` controls the readiness deadline. The app runs with one CPU, 512 MiB container memory and a 256 MiB maximum heap. JVM modes use G1 with explicit code-cache, metaspace, direct-memory and stack budgets and a memory-calculator thread budget of 50 so their settings fit the 512 MiB limit; native uses Serial GC.

For JVM examples, `project.toml` supplies the literal space separating appended `JAVA_TOOL_OPTIONS`; `pack` trims this value in env files. The thread budget is an explicit override so Spring Boot's default of 250 does not replace it. The benchmark checks container state while waiting for readiness and reports an early exit with its JVM/app logs instead of waiting for the full timeout.

Omit `EXAMPLE` to select with fzf; use `brew install fzf` on macOS if needed. Numbers `01`–`04` or full directory names skip the picker. Multiple selected goals share one selection. `make compare` builds and measures all four without a picker. `make clean` removes Compose containers and networks while keeping images, build caches and results.

## Build tools and registries

Defaults are `buildpacksio/pack:0.40.9`, `paketobuildpacks/builder-noble-java-tiny:latest` and `python:3.13-slim`. Builder/helper tags can change; for reproducible builds, set them to reviewed digest references. Build logs and image/buildpack metadata record the inputs used. Pack and the helper containers mount the Docker socket to create builder or benchmark containers.

The build script resolves relevant registry logins from your host Docker configuration and credential helpers (including Docker Desktop). It mounts a temporary Docker config read-only into the pack container and removes it when the build exits. Credentials are never included in the application source, build logs or results. If Docker Desktop reports `Enforced sign-in` or `Pull failed due to an unauthenticated request`, make sure you are signed into Docker Desktop and run `docker login` in your terminal before repeating `make bench`. Use your registry's normal login command when overriding the builder with a private registry image.

```sh
make build EXAMPLE=01 BUILDER=your-registry.example.com/java-builder@sha256:YOUR_DIGEST
make build EXAMPLE=04 PLATFORM=linux/amd64
```

`PACK_IMAGE`, `HELPER_IMAGE` and `DOCKER_SOCKET` can also be overridden for your environment. An organization restricting Docker Hub must provide approved access or registry-hosted equivalents of the pack, builder, run and helper images. The builder's metadata determines the run image and buildpacks it uses. Network access is also needed for Gradle distributions and application/compiler dependencies. The default build platform comes from the Docker server; explicitly select the platform that matches your Kubernetes nodes. Native images and JVM caches are platform-specific.

## Benchmarks and reports

```sh
make bench EXAMPLE=01 RUNS=10 WARMUPS=2
make compare RUNS=10 WARMUPS=2
```

The shared [benchmark](benchmark/README.md) launches fresh containers, verifies their responses and prints a comparison table with median startup, p95 startup and median container memory. Build/pull/creation time is excluded; container start, the buildpack launcher and 20 ms readiness polling are included. Memory is container working set near readiness, including all processes; it is not application process RSS. These measurements have a different scope from the original project's process-only benchmarks. Use comparisons within this project. This harness measures startup, not sustained-load performance or Kubernetes scheduling/image-pull time.

Single-example reports go under `results/<numbered-example>/<UTC timestamp>/`; combined reports go under `results/comparison/<UTC timestamp>/`. Each directory contains `report.html` and an `artifacts/` subdirectory for CSV/JSON, logs, image metadata and build evidence. The terminal prints a host `file://` link; compatible terminals make it clickable. Tables use colored headers when supported, with `NO_COLOR` and `FORCE_COLOR` overrides. All `results/` content is ignored by Git. Failed checks produce diagnostics and fail the command; no successful comparison is published.

## Kubernetes

Every example owns a Deployment, Service and Kustomization under `k8s/`. Probes use HTTP directly and do not require a shell or curl in the application image. The startup probe gates readiness while the service initializes. The manifests use one replica, a one-CPU limit and 512 MiB memory, and separate names/selectors for each example.

For a local kind cluster, build the image, load it into your chosen cluster, review the manifests and apply them yourself:

```sh
make build EXAMPLE=01
kind load docker-image aot-buildpacks/01-spring-java-baseline:local --name YOUR_CLUSTER
make render-k8s EXAMPLE=01
kubectl apply -k examples/01-spring-java-baseline/k8s
kubectl port-forward service/catalog-01 8080:8080
```

Then `curl -sS http://localhost:8080/ready` or use the other endpoints. For a remote cluster, build with your registry image name, push it and render manifests referencing that exact image:

```sh
make build EXAMPLE=01 IMAGE=your-registry.example.com/catalog:baseline
# Authenticate to your registry using its normal login workflow before pushing.
docker push your-registry.example.com/catalog:baseline
make render-k8s EXAMPLE=01 IMAGE=your-registry.example.com/catalog:baseline > /tmp/catalog-01.yaml
kubectl apply -f /tmp/catalog-01.yaml
```

Registry credentials and cluster access belong to your environment. Make commands render manifests but never apply them or publish images automatically. Kubernetes uses the buildpack image's default launcher, so its runtime/AOT settings are retained.

For optional local development, each example's `./gradlew build` needs Java 25. Shared helper checks can be run with `python3 -m unittest discover -s tests -v`.

Official references: [Cloud Native Buildpacks](https://buildpacks.io/docs/), [containerized pack CLI](https://buildpacks.io/docs/for-platform-operators/how-to/integrate-ci/pack/), [Paketo Gradle configuration](https://github.com/paketo-buildpacks/gradle), [Spring buildpack settings](https://github.com/paketo-buildpacks/spring-boot), [AOT cache support](https://docs.spring.io/spring-boot/how-to/aot-cache.html), [Native Image buildpack](https://github.com/paketo-buildpacks/native-image).
