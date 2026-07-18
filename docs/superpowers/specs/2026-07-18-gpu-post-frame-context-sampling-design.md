# GPU Post-Frame Context Sampling Design

## Goal

Restore offscreen GPU-to-CPU sampling after the frame is complete, while giving every GPU backend one common renderer lifecycle interface. The device will dispatch post-frame processing to every context that participated in the frame, with `m_pgpucontextMain` deliberately called last.

This keeps sampling out of `graphics3d::engine`: the engine renders layers, while the GPU framework owns frame completion and output transfer.

## Renderer interface

`gpu::renderer` will expose a virtual `on_end_frame()` lifecycle method. Its base implementation will inspect the renderer context output mode. When the output is `e_output_cpu_buffer`, it will invoke a second virtual method, `sample_to_cpu_buffer()`. GPU-buffer and swap-chain outputs will not perform CPU sampling by default.

Each backend will implement `sample_to_cpu_buffer()` by forwarding to its existing, proven readback operation:

- OpenGL: `do_sampling_to_cpu()`
- DirectX 11: `do_sampling_to_cpu()`
- Vulkan: `sample()`
- DirectX 12: `sample()`

The common name removes backend-specific knowledge from the frame lifecycle. The existing backend methods may remain as implementation details to keep this change focused.

## Context interface

`gpu::context` will expose `on_end_frame()`. It will forward post-frame processing to its renderer when one exists. This is the device-facing interface and leaves backend selection inside the context and renderer objects.

`gpu::context::start_layer()` will register the context and active layer with its device for the current frame. Re-registering a context will update its associated layer to the most recently used layer without changing the context's first-use ordering.

Recording the layer is necessary because existing Vulkan and DirectX 12 sampling code obtains render-target state through the current GPU layer. Before dispatching a context, the device will temporarily make that context's recorded layer current. This prevents one context from sampling another context's render target.

## Device participation and ordering

At `device::start_frame()`, the device will clear the prior frame's participating-context records.

At `device::end_frame()`, after the existing device and frame completion bookkeeping, the device will:

1. take a stable snapshot of the participating contexts and their most recent layers;
2. call `on_end_frame()` for each participating context other than `m_pgpucontextMain`, in first-use order;
3. call `m_pgpucontextMain->on_end_frame()` last, whether or not it was registered as a participating context;
4. restore the previously current GPU layer after dispatch.

Each context is called at most once. Holding strong framework pointers in the frame records keeps contexts and layers alive until dispatch has completed.

The snapshot will be formed while protecting the device's context list, but callbacks and GPU-to-CPU sampling will run without that lock held. This avoids deadlocks when completion publishes an image and schedules a GUI redraw.

Calling the main context last is an explicit ordering policy for this change. It provides a stable final device-level hook while the framework's broader frame responsibilities continue to evolve.

## Error handling

Post-frame processing should make a best effort to notify all eligible contexts, including the main context last. If a context throws, the device will retain the first exception, continue the remaining callbacks, restore the prior current layer, and then rethrow the first exception.

This preserves the main-last contract and prevents a failing secondary context from silently skipping required final processing.

## Offscreen data flow

The graphics3d CPU-buffer context participates when its layer starts. At device frame completion, that non-main context receives `context::on_end_frame()`, which calls `renderer::on_end_frame()`. Because its output is `e_output_cpu_buffer`, the renderer dispatches to the backend's sampling method. The backend updates the target image, whose existing completion callback requests the GUI redraw. The main GPU context is then processed last and performs no CPU sampling when its output mode does not require it.

The on-screen swap-chain path follows the same lifecycle but does not read pixels to the CPU because its output mode is not `e_output_cpu_buffer`.

## Compatibility and scope

This change does not alter the draw order, swap-chain presentation, offscreen FPS pacing, or GUI image callback. It only restores and centralizes post-frame output handling.

No shader or cubemap behavior is involved. No backend-specific sampling policy will be placed in `graphics3d::engine` or `gpu::device`.

## Verification

Focused tests will cover:

- CPU-buffer renderer output dispatching exactly one sampling call;
- GPU-buffer and swap-chain output skipping CPU sampling;
- participating contexts being deduplicated;
- non-main contexts retaining first-use order while their latest layer is used;
- the main context being invoked exactly once and last;
- the current GPU layer being restored after dispatch;
- all contexts being attempted and the first exception being rethrown.

The affected framework and OpenGL, Vulkan, DirectX 11, and DirectX 12 renderer projects will then be built. The final behavioral check is the OpenGL offscreen `shared_app_graphics3d_continuum` run: the sampled 3D image should again appear inside the GDI+ window hierarchy while memory remains stable under the FPS limiter.
