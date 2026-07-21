# Pooled Graphics and GPU Context Leases

## Purpose

Remove the accidental one-image/one-graphics/one-GPU-context/one-thread ownership pattern from GPU-backed images. Replace it with exclusive, move-only leases over centrally pooled graphics and GPU contexts. Apply the first vertical slice to font enumeration and preview rendering, where the current CPU-era parallel design creates many heavyweight FullHD GPU memory contexts.

## Current Problem

`image::get_graphics()` lazily creates and stores a `draw2d::graphics`. When the active implementation is GPU-backed, that graphics can own a `gpu::context`, and every `gpu::context` is a thread. Collections containing many images can therefore produce graphics, contexts, and threads proportional to image count.

Font enumeration amplifies the problem. Its two parallel extent-calculation phases create memory graphics per worker. Memory graphics currently default to a 1920x1080 backing surface, and NanoVG memory graphics create an offscreen GPU context and a NanoVG context. WGL creation is correctly serialized for safety, so the parallel workers queue while creating many expensive contexts.

The existing runtime diagnostics have ruled out the NanoVG image fast path as the dominant cost: observed font-enumeration traces had no CPU image fallback, no image mapping, no pending fence waits, and negligible NanoVG wrapper time. The remaining expensive work occurs before the font list reaches its drawing diagnostics.

## Ownership Model

An `image::image` owns image content only:

- dimensions, format, and metadata;
- CPU pixmap storage when mapped;
- GPU texture/resource when GPU-backed; and
- optional non-owning device or context-affinity metadata.

An image does not own a `draw2d::graphics`, `gpu::context`, or GPU-context thread.

`draw2d::draw2d` owns the graphics pool. `gpu::device` owns the GPU-context pool.

```text
draw2d::draw2d
  `- graphics pool
       `- draw2d::graphics_lease
            `- pooled draw2d::graphics
                 `- gpu::context_lease (for GPU graphics)
                      `- gpu::device context pool
                           `- gpu::context + thread

image::image
  `- pixel/texture resource only
```

## Lease Types

### `draw2d::graphics_lease`

`draw2d::graphics_lease` is move-only and pointer-like. It represents exclusive access to one graphics object. It may be kept on the stack for a short operation or stored as a member when persistent ownership is intentional, such as inside a graphics buffer.

Typical use:

```cpp
auto graphicslease = pimage->acquire_graphics();

graphicslease->fill_rectangle(...);
graphicslease->text_out(...);
```

Acquisition delegates to `draw2d::draw2d`. The pool finds a compatible idle graphics object or creates one. The graphics is exclusively bound to the target image before the lease is returned.

Releasing the lease:

1. finishes recording and submits pending drawing;
2. inserts any resource fence required by the backend;
3. unbinds the target image;
4. resets transient graphics state; and
5. returns the graphics object to its pool.

The lease keeps a strong image reference while the target is bound. The image stores no owning reference back to the graphics.

### `gpu::context_lease`

`gpu::context_lease` is also move-only. It represents exclusive ownership of a pooled context from `gpu::device`. Keeping the lease in a member makes the association persistent; releasing it returns the context to the device pool.

A pooled GPU-backed `draw2d::graphics` retains its `gpu::context_lease` while the graphics is idle. This preserves its context thread, NanoVG context, and other expensive backend state as a warm reusable bundle. Idle eviction and least-recently-used cleanup are explicitly deferred from the first implementation.

## Pool Compatibility and Scope

The first implementation pools memory/offscreen graphics. Window and swapchain graphics remain persistent because they are tied to presentation and window lifecycle.

A graphics entry is compatible when it matches the required:

- draw2d backend;
- GPU device and resource-sharing family;
- memory/offscreen output capability; and
- render-target format and backend requirements.

Image size is acquisition state rather than a permanent pool key. A compatible graphics object may resize or reconfigure its offscreen target before binding the image.

The general pool grows with genuinely concurrent leases rather than image count. Sequentially drawing thousands of images reuses a small warm set. Persistent leases intentionally contribute to active pool size. The first implementation records pool high-water marks; automatic idle eviction is deferred.

Font measurement is a deliberately bounded special case: it uses one persistent graphics lease for the complete GPU-dependent extent phase. CPU-only font metadata discovery may remain parallel, but GPU font creation and text measurement are serialized on the one leased context thread. This prevents `fork_count()` from turning CPU affinity into GPU-context count.

## Threading and Image Exclusivity

Pool operations are synchronized. A lease is the exclusive authority to use its graphics or context object.

An image permits only one active destination-drawing lease. Mapping, resizing, destroying, or acquiring another destination lease for the same image must wait or fail clearly rather than race. Sampling an image produced by a released graphics lease observes the backend fence established during release.

GPU operations continue to execute on the leased graphics object's context thread through the existing context dispatch mechanisms. A graphics object is not made available to another borrower until its release sequence has completed.

Lease destructors do not throw. An explicit `close()` may report cleanup or submission failures. Destructor cleanup catches and logs errors, marks the underlying resource damaged, and removes that resource from pool reuse.

During shutdown, pools reject new acquisitions. Idle resources are destroyed immediately. An outstanding lease destroys rather than returns its resource when it is eventually released into a shutting-down pool.

## Incremental API Migration

The codebase contains hundreds of `g()` and direct `get_graphics()` call sites across multiple implementations and platforms. Removing all persistent implementation machinery in a single change would be unnecessarily broad.

The migration proceeds in phases.

### Phase 1: Introduce leases and break shorthand usage

- Add the graphics and context pools and their move-only lease types.
- Add `image::acquire_graphics()`.
- Rename the short `g()` alias to `g2()` so existing shorthand usages fail to compile and new code cannot silently retain the old ownership model.
- Retain direct `get_graphics()`, backend `_get_graphics()`, and persistent implementation fields temporarily as explicitly legacy paths.
- Do not introduce new `g2()` or direct `get_graphics()` usages.

Call sites are migrated according to intent:

- a single destination operation receives a scoped graphics lease;
- a sequence of destination operations shares one scoped lease;
- genuinely persistent graphics ownership stores a lease member;
- source-image operations pass an image or texture directly where possible instead of acquiring source graphics; and
- low-level backend paths use explicit resource access rather than extending a graphics lease beyond its scope.

### Phase 2: Remove persistent image graphics

Remaining `g2()` and direct `get_graphics()` users are migrated module by module. When no compatibility user remains, remove `image::m_pgraphics`, `get_graphics()`, `_get_graphics()`, and `g2()`.

## Font Enumeration Vertical Slice

Font enumeration is the first end-to-end migration and performance correction.

1. Acquire one measurement graphics lease before GPU-dependent extent calculation begins.
2. Reuse that lease across both existing extent-calculation phases.
3. Keep CPU-only metadata enumeration parallel where useful.
4. Execute GPU-dependent font creation, character-set queries, and `get_text_extent()` sequentially on the measurement graphics context thread.
5. Perform layout after the measurements complete.
6. Release the measurement lease after measurement and layout.

Font preview generation also migrates:

1. `text_box::update()` creates or resizes the preview image resource without creating persistent graphics.
2. It acquires a short graphics lease bound to the preview image.
3. It draws the background and text.
4. It releases the lease, making the completed texture available for GPU-only list drawing.

Many preview images consequently share a small warm set of graphics/context objects and retain no graphics, context, or thread individually.

## Runtime Diagnostics

The existing runtime GPU performance setting also controls the new reports.

`[draw2d.graphics_pool]` reports:

- acquisitions;
- reuse and creation counts;
- active and idle entries; and
- pool high-water mark.

`[gpu.context_pool]` reports:

- acquisitions;
- reuse and creation counts;
- active and idle entries; and
- live context-thread count.

`[gpu.performance.font_enumeration]` reports:

- CPU metadata duration;
- measurement-graphics acquisition duration;
- font creation count and duration;
- extent-query count and duration; and
- total enumeration duration.

Diagnostics default to disabled and follow the existing runtime reporting interval. The disabled hot path must not perform clock reads, formatting, allocation, or counter updates beyond the existing relaxed enabled-flag check.

## Failure Handling

An acquisition failure returns no partial lease. If graphics initialization, target binding, context initialization, or cleanup fails, the affected graphics/context object is marked damaged and excluded from subsequent reuse.

Concurrent destination acquisition, mapping, or resize conflicts produce an explicit wrong-state result rather than undefined behavior. Pool shutdown and device loss reject new leases and retire returned resources.

## Verification

Focused tests must verify:

- graphics and context leases are move-only;
- released compatible resources are reused;
- persistent leases remain unavailable until released;
- concurrent destination leases for one image are rejected or serialized;
- mapping and resizing cannot race with active drawing;
- returned graphics have no bound target and reset transient state;
- warm pooled GPU graphics retain their context leases;
- damaged resources are destroyed instead of reused;
- shutdown handles idle and outstanding leases safely;
- font enumeration uses one measurement graphics lease across both extent phases;
- font preview images retain no graphics/context/thread objects;
- NanoVG preview drawing remains GPU-only without CPU mapping;
- preview transparency and colors remain correct; and
- Continuum remains responsive during enumeration and scrolling.

The initial performance acceptance criterion is architectural rather than a fixed duration: font enumeration must no longer create graphics, GPU contexts, or threads proportional to CPU affinity or image count. Diagnostics must demonstrate one warm measurement graphics/context bundle for the GPU-dependent extent phase and reuse for sequential preview generation.

## Deferred Work

The first implementation does not add:

- idle-time or least-recently-used pool eviction;
- adaptive pool limits;
- multiple parallel font-measurement contexts;
- pooling for window/swapchain graphics; or
- immediate removal of every legacy backend `get_graphics()` implementation.

These can be evaluated after the pooled ownership model is stable and runtime diagnostics show actual resource demand.
