# 04 — Spring AOT and GraalVM Native Image

## Setup and changes from the baseline

- **Setup:** This independent Gradle 9.1.0 / Java 25 / Spring Boot 4.1.1 project owns its catalog source, resources, tests, wrapper, buildpack settings, Compose file and Kubernetes manifests. Pack and Paketo produce the application image from source without an application Dockerfile.
- **Baseline:** Example 01 defines the ordinary JVM reference. This project owns the same application source and contract; it does not import or build Example 01. All four applications use one CPU, 512 MiB container memory and a 256 MiB maximum heap.
- **What changes and why:** The Gradle build generates Spring initialization and runtime hints. `BP_NATIVE_IMAGE=true` asks Paketo to compile the processed application using Native Image. Native compilation uses no fallback, Serial GC, compatibility CPU instructions, two threads, a 4 GiB compiler heap and a 256 MiB runtime heap default. Explicit hints cover the bundled catalog, dynamic policy method and Logback configurators. There is no HotSpot cache in this executable.
- **Expected result:** Identical catalog and metadata responses, with potentially much faster readiness and lower runtime memory. `/ready` must report Spring AOT and generated initialization enabled. Build time and memory requirements increase, and the executable must match the node architecture. The benchmark checks responses and measures improvements rather than assuming them.

## Build, test and stop

From the repository root:

```sh
make build EXAMPLE=04
make test-app EXAMPLE=04
make clean EXAMPLE=04
```

`make test-app` includes building, waits for readiness and verifies sample HTTP responses. It prints curl commands and formatted JSON and leaves the service running for manual requests. Set `PORT=8084` to avoid another app on port 8080; use the same port when repeating the command. `ITERATIONS` defaults to 100,000. Omit `EXAMPLE` for fzf selection. `make clean` preserves images, caches and results.

The source loads eight products from `catalog.csv`, calculates quotes using integer cents and runs a deterministic computation. Endpoints are `/ready`, `/products/1`, `/quotes`, `/compute?iterations=100000` and `/native-metadata`. See [the root README](../../README.md) for the contract, build-tool requirements and manual requests.

[buildpack.env](buildpack.env) contains the explicit buildpack choices. Gradle's build arguments run Java tests before packaging. [build.gradle](build.gradle) and the pinned [wrapper properties](gradle/wrapper/gradle-wrapper.properties) belong to this project. Default builder/helper tags can move; pass reviewed digest references through `BUILDER`, `PACK_IMAGE` and `HELPER_IMAGE` for reproducibility. Build evidence is ignored under `results/04-spring-aot-graalvm-native/build-artifacts/`.

## Measure and deploy

```sh
make bench EXAMPLE=04 RUNS=10 WARMUPS=2
make compare RUNS=10 WARMUPS=2
make render-k8s EXAMPLE=04
```

The benchmark prints startup and median container memory and writes `results/04-spring-aot-graalvm-native/<UTC timestamp>/report.html`, with evidence in `artifacts/`. Its startup window includes the container start and buildpack launcher; memory is container working set near readiness. These are different measurements from the original Dockerfile repo's process-only statistics. Builds and pulls are excluded from timing. See the [benchmark method](../../benchmark/README.md).

The owned [Kubernetes manifests](k8s/) define Deployment `catalog-04` and Service `catalog-04`, with HTTP startup/readiness probes and matching resource limits. Load the image into your local cluster or publish it to your registry, then apply the reviewed manifests yourself. `IMAGE=your-registry.example.com/catalog:04` controls both the built image and `make render-k8s`; `PLATFORM` must match your nodes. Commands and registry details are in the root README. Make never publishes or applies manifests automatically.
