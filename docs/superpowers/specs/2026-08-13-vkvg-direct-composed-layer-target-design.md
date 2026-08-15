# VKVG Direct Composed-Layer Target Design

## Goal

Make `draw2d_vkvg` render directly into the ca2 `gpu_vulkan` layer texture whenever the active layer has `m_bIncludeInFrameComposition == true`. The texture sampled later by `merge_layers()` must be the same `VkImage` that vkvg rendered.

This change follows the target-selection behavior already used by `draw2d_nanovg`: a composed layer uses the renderer's current layer texture instead of a private draw2d backend target.

## Scope

The implementation and verification cover only layers for which `m_bIncludeInFrameComposition` is true.

The existing vkvg-owned surface behavior remains present for other graphics uses, but this work does not refactor, extend, or add tests for the false case. `set_target_image()` is not part of the new path.

The change does not restore `layer_end_copy()`, add an intermediate image copy, or change the merge shader. The intended architecture remains direct-to-layer.

## Existing Behavior and Root Cause

`draw2d_nanovg` obtains the active composed layer texture through `current_target_texture()`, binds that OpenGL texture's framebuffer, and executes `nvgBeginFrame()` and `nvgEndFrame()` against it.

`draw2d_vkvg` instead creates a private `VkvgSurface` with `vkvg_surface_create()`. Its `VkvgContext` is permanently associated with that surface, and `current_target_texture()` exposes the private surface's final image through a ca2 texture wrapper. Consequently, the image rendered by vkvg is not necessarily the ca2 layer image later supplied to `merge_layers()`.

Vulkan adds another conflict that OpenGL NanoVG does not have. The ca2 Vulkan renderer normally records a clear and render pass for every layer. If vkvg independently renders the same `VkImage`, the later ca2 submission can clear or overwrite the vkvg result. A directly rendered vkvg layer must therefore bypass ca2's ordinary render-pass recording and submission for that layer.

## Target Selection

`draw2d_vkvg::graphics::current_target_texture()` follows the NanoVG rule:

1. When `pgpulayer` is non-null and `pgpulayer->m_bIncludeInFrameComposition` is true, return the current render-target texture selected by the ca2 renderer for that layer.
2. Otherwise, leave the existing private vkvg-surface wrapper path unchanged.

The selected composed-layer target must be a `gpu_vulkan::texture` with:

- a valid `VkImage`;
- `VK_FORMAT_B8G8R8A8_UNORM`, which matches the current vkvg framebuffer format;
- one color layer and one mip level for this integration path;
- `VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT` and `VK_IMAGE_USAGE_SAMPLED_BIT`;
- dimensions matching the active drawing extent.

An incompatible target fails at preparation time with a descriptive wrong-state or unsupported-format exception. It must not silently fall back to the private vkvg image, because that would recreate the empty composed-layer texture failure.

## External Layer Rendering Contract

Add a backend-neutral compositor query that reports whether a layer's rendering is owned by an external graphics backend rather than the ca2 renderer's render pass. The default implementation returns false. `draw2d_vkvg::graphics` returns true only when the layer exists and `m_bIncludeInFrameComposition` is true.

The selected value is stored on the layer for the complete start/end lifecycle. For an externally rendered layer, the generic renderer must retain layer and frame bookkeeping but must not:

- call the backend's ordinary `on_begin_render()` or `_on_begin_render()` path;
- record the ca2 layer clear or begin a ca2 render pass;
- call the matching backend `_on_end_render()`;
- insert a fence into a ca2 layer command buffer that was never recorded;
- call `layer_end_submit()` for that nonexistent ca2 command buffer.

The compositor start and end hooks still run. The layer still moves through its began-render and ended-render bookkeeping states, and the normal layer stack remains available to `merge_layers()`.

This bypass is determined before Vulkan begins recording the ordinary layer command buffer. It is not applied retroactively after a render pass has opened.

The generic context resolves the layer texture and finalizes its placement, raw size, and drawing extent before invoking the compositor start hook. The hook can therefore validate and wrap the exact texture that the rest of the frame will identify as that layer's composition input.

## Wrapping a ca2 VkImage for vkvg

ca2 fabricates and owns the `VkhImage` passed to the existing `vkvg_surface_create_for_VkhImage()` API. No new vkvg constructor or source patch is added. On Windows, the wrapper's module-definition file exports the four existing Vkh entry points ca2 needs: `vkh_image_import`, `vkh_image_status`, `vkh_image_create_view`, and `vkh_image_destroy`.

The adapter uses `vkh_image_import()` with a stable `VkhDevice` view over `gpu_vulkan::device::m_vkdevice`, matching vkvg's own internal convention of treating the address of a persistent `VkDevice` member as the leading portion of a Vkh device. It then creates the required 2D color view and passes the resulting `VkhImage` to `vkvg_surface_create_for_VkhImage()`.

The direct-target cache entry retains the `gpu_vulkan::texture`, `VkhImage`, `VkvgSurface`, and `VkvgContext`. Destruction occurs in this exact order:

1. destroy the `VkvgContext`;
2. destroy the `VkvgSurface`;
3. call `vkh_image_destroy()` on the ca2-owned imported wrapper;
4. release the retained ca2 texture.

The existing vkvg surface destructor deliberately does not destroy an imported `VkhImage`. The final ca2-owned `vkh_image_destroy()` releases the wrapper, view, and sampler while the imported flag prevents destruction of the ca2 `VkImage` or its memory. The pinned `port/graphics3d/vkvg/vkvg` submodule and wrapper patch series remain unmodified; only the wrapper-owned Windows export list changes.

## Surface and Context Cache

A `VkvgContext` cannot be redirected by binding another framebuffer as NanoVG can. It is tied to its `VkvgSurface`. `draw2d_vkvg` therefore maintains a small cache of direct-target entries, one for each rotating ca2 layer image.

Each entry contains:

- a retained pointer to the owning `gpu_vulkan::texture`;
- the `VkImage`, format, width, and height used as its identity;
- the ca2-owned imported `VkhImage` wrapper;
- the imported `VkvgSurface`;
- the corresponding `VkvgContext`;
- the most recent frame serial in which the entry was used.

`prepare_vkvg_render_target()` looks up the selected texture and makes its surface/context the active pair used by all existing draw2d operations. It creates an entry only on a cache miss. If the same ca2 texture object has been recreated with a different image handle, format, or size, the stale entry is destroyed and replaced.

Destruction order is context, surface, imported `VkhImage`, then retained ca2 texture reference. Cache cleanup occurs before the shared vkvg device is released. Because one draw2d_vkvg graphics instance can serve multiple composed layers, cache capacity is `frame count * composed layer count + 1`, retaining one entry for every rotating physical layer image plus a small allowance. Entries unused beyond that bound are evicted only after their vkvg work is complete.

The existing private `m_vkvgsurface` and `m_vkvgcontext` remain available for the out-of-scope non-composed path. Direct-target entries do not replace or transfer ownership of them.

## Vulkan Image State and Synchronization

Vkvg and ca2 share the same Vulkan logical device, graphics queue family, and graphics queue. The existing queue host-call mutex remains locked across the draw2d layer so vkvg queue submissions and ca2 queue submissions cannot be issued concurrently from different host threads.

On a cache hit, before vkvg starts rendering the direct target, ca2 transitions the selected image from its tracked current state, normally shader-read after the previous composition, to:

```text
access: COLOR_ATTACHMENT_WRITE
layout: COLOR_ATTACHMENT_OPTIMAL
stage:  COLOR_ATTACHMENT_OUTPUT
```

This transition is submitted before vkvg work on the shared graphics queue. On a cache miss, the implementation first waits for any existing target-reuse fence required by the render-target rotation contract. The new imported surface may then transition the raw image from `UNDEFINED`, discarding prior color contents, because the layer is cleared before drawing. After that first-use transition, ca2 synchronizes its tracked metadata to the resulting color-attachment state. It does not submit a redundant ca2 transition before creating the imported surface.

Vkvg's cached `VkhImage` continues to regard the image as `COLOR_ATTACHMENT_OPTIMAL`. Although ca2 temporarily transitions it to shader-read during `merge_layers()`, ca2 transitions it back to color-attachment state before the next vkvg submission. Vkvg therefore never operates while its internal layout bookkeeping disagrees with the actual layout.

At `end_layer()`, `vkvg_flush()` submits all pending drawing. The ca2 texture's tracked state is then synchronized to vkvg's final state of color-attachment write in `COLOR_ATTACHMENT_OPTIMAL`. The later merge command buffer performs the ordinary transition to shader-read and samples the image. Queue ordering plus that transition provides the dependency from vkvg color writes to merge fragment-shader reads; no CPU readback or image copy is introduced.

If future configuration places vkvg and composition on different queues, this same-queue contract must be replaced with explicit semaphore synchronization. Supporting that configuration is outside this change.

## Layer Lifecycle

For a composed vkvg layer, the sequence is:

1. Create/select the ca2 layer and determine that vkvg owns its rendering.
2. Preserve generic layer bookkeeping while skipping ca2's ordinary layer render pass.
3. Resolve and validate the current ca2 layer texture.
4. Complete any required target-reuse wait.
5. Select the cached `VkvgSurface`/`VkvgContext` and transition a reused image back to color-attachment state, or create a new pair whose first-use transition discards the old contents.
6. Clear through vkvg and perform draw2d operations through the active context.
7. Flush vkvg before ending the layer.
8. Synchronize ca2's tracked texture state to vkvg's final color-attachment state.
9. Keep the layer texture in the layer stack for direct sampling by `merge_layers()`.

Failure after acquiring the queue host-call lock must release the lock and leave no partially active cache entry. A cache entry is published only after both surface and context creation succeed.

## Diagnostics

Focused trace messages should make the direct path inspectable without RenderDoc. At minimum, start and end diagnostics identify:

- layer index and `m_bIncludeInFrameComposition`;
- ca2 texture pointer and raw `VkImage`;
- selected `VkvgSurface` and `VkvgContext`;
- cache hit or miss;
- image layout/access before handoff and after vkvg flush;
- whether the ca2 render-pass path was bypassed.

The diagnostics must not run per draw primitive. They are temporary or debug-level once the integration is verified.

## Testing and Verification

Testing is intentionally limited to the `m_bIncludeInFrameComposition == true` path.

Failing-first contract coverage verifies:

1. `draw2d_vkvg::current_target_texture()` selects the ca2 layer target for a composed layer.
2. ca2 fabricates a `VkhImage` over the exact layer `VkImage` and passes it to `vkvg_surface_create_for_VkhImage()` without modifying vkvg.
3. ca2 destroys the imported wrapper only after its context and surface; the wrapper releases its view/sampler bookkeeping but never destroys the ca2 image.
4. The external-layer branch skips ca2 begin-render, clear, render-pass end, command-buffer fence insertion, and submission while preserving layer bookkeeping.
5. `prepare_vkvg_render_target()` caches by image identity and replaces stale entries after resize/recreation.
6. The end-layer handoff records the vkvg color-attachment final state for later shader sampling.

Build verification covers the vkvg wrapper, `draw2d_vkvg`, `gpu_vulkan`, and `shared_app_graphics3d_continuum` in the requested Windows configuration.

Runtime verification uses `draw2d_vkvg` with `gpu_vulkan` and confirms:

- Vulkan validation reports no render-pass, image-layout, queue-synchronization, or pipeline-binding errors;
- traces show the same raw `VkImage` at vkvg target selection and `merge_layers()` input binding;
- the 2D UI appears over the 3D scene;
- no `layer_end_copy()` operation is required.

RenderDoc is optional. If used, it should confirm image identity rather than being required for the offscreen workflow.

No new test or implementation work is required for `m_bIncludeInFrameComposition == false` in this task.
