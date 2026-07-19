# Runtime GPU Performance Diagnostics Design

Date: 2026-07-19

## Purpose

Add permanent, runtime-configurable performance diagnostics for the GPU-backed font-preview path. The diagnostics must distinguish CPU image transfers from font-preview generation, GPU synchronization, and NanoVG texture-wrapper overhead without changing rendering behavior.

## Runtime configuration

The application GPU settings will contain two thread-safe public settings:

- Performance diagnostics enabled, defaulting to `false`.
- Reporting interval in milliseconds, defaulting to `1000`.

The graphics3d engine will expose public setters and getters for these settings. Changing either setting while rendering is active takes effect without restarting the engine. The reporting interval will be clamped to the inclusive range from 100 to 60,000 milliseconds.

The application GPU settings are the shared source of truth because font enumeration and draw2d graphics may be created outside the direct ownership of a graphics3d engine. This avoids process-global configuration and avoids propagating an engine-owned diagnostics object through every GPU context.

## Metrics

### Font-list metrics

Each font list will aggregate:

- Drawing passes.
- Font items examined.
- Visible font items.
- Preview images generated or regenerated.
- Cached preview images drawn.
- Time spent generating preview images.
- Time spent submitting cached preview draws.

These counters will reveal whether scrolling regenerates previews, examines the entire list, or spends most of its time drawing already cached images.

### NanoVG GPU-image metrics

The NanoVG drawing implementation will aggregate:

- GPU-image fast-path draws.
- CPU fallback draws.
- NanoVG OpenGL texture-wrapper creations and deletions.
- Draws that encountered a pending OpenGL fence.
- Total time spent waiting for fences.
- Total time spent creating and deleting NanoVG wrappers.

The diagnostic must separately count a pending fence before calling `wait_fence()`. A fence call that immediately returns because no fence exists is not counted as a wait.

### GPU-image mapping metrics

The common GPU image implementation will aggregate:

- Actual map transitions from GPU-only to CPU-mapped state.
- Actual unmap transitions from CPU-mapped to GPU-only state.
- Bytes read from GPU textures.
- Bytes uploaded to GPU textures.
- Total readback and upload duration.

Calls that find the image already in the requested state remain no-ops and are not counted as transitions.

To associate mapping operations, bounded detailed transition records will include:

- A global transition sequence.
- Image pointer.
- Texture pointer.
- Image dimensions.
- Current task name or identifier.
- Operation (`map` or `unmap`).
- A per-image mapping generation shared by the matching map and unmap.

Detailed transition records are capped at the first 64 transitions after diagnostics are enabled so persistent diagnostics cannot flood the log. Disabling and re-enabling diagnostics resets this detail allowance. Aggregate reports continue after the detail cap is reached.

## Reporting

Each subsystem owns its counters and emits a tagged aggregate report when its next configured reporting interval expires. Reports use deltas for the interval rather than ever-growing totals. Logging and timing are skipped entirely while diagnostics are disabled.

The reports use stable tags:

- `gpu.performance.font_list`
- `gpu.performance.nanovg_image`
- `gpu.performance.image_mapping`

Relaxed atomic operations are sufficient for counters because diagnostics do not control rendering or synchronization. Report emission will use an atomic deadline or a small subsystem-local synchronization so only one thread consumes each interval's counters.

Disabling diagnostics clears pending interval counters and timing state. Re-enabling begins a fresh interval so stale work is not attributed to the new measurement window.

## Performance constraints

When diagnostics are disabled, hot paths perform only a single relaxed flag load before returning. They do not read clocks, increment counters, allocate memory, or format strings.

When enabled, instrumentation uses aggregated counters and monotonic clock measurements. It does not emit a message for every GPU draw. Individual messages are limited to actual map/unmap transitions and stop after the fixed detail cap.

## Testing

Source-level contract tests will verify:

- Diagnostics default to disabled with a one-second interval.
- Runtime engine accessors update the shared application GPU settings.
- No-op map and unmap calls are excluded before transition accounting.
- GPU fast-path diagnostics distinguish pending fence waits from no-fence calls.
- Font-list instrumentation distinguishes preview generation from cached drawing.
- Stable report tags are present.

Existing GPU-image mapping, NanoVG fast-path, and font-list builds must continue to pass. The full `shared_app_graphics3d_continuum` Debug x64 target will be built after the focused tests.

## Scope

This change adds measurement only. It does not reorder font-list visibility checks, cache NanoVG image handles, change fence behavior, change image alpha handling, or otherwise optimize rendering. Performance improvements will be selected from measured evidence in a subsequent change.
