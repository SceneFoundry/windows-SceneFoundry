# GPU Memory-Image Layer Composition Design

## Problem

When a GPU-backed `image::image` is rendered on demand, its acquired `gpu::graphics` opens a scoped layer and renders the image into an offscreen GPU texture. That layer is also inserted into the device-wide frame layer array.

At the end of the window frame, `gpu::renderer` currently copies and merges every layer in that array. The image-rendering layer therefore appears once at its texture's default rectangle `(0, 0, width, height)`, even though the same texture is subsequently drawn at its correct destination through the explicit image-drawing path.

This explains the observed behavior in the font list:

- a normal font preview appears once at `(0,0)` when scrolling first causes that preview to be cached;
- the larger hover preview appears once at `(0,0)` on its first hover;
- later draws are correctly placed because they reuse the already-rendered cache texture and do not create another image-rendering layer.

The render target contents and NanoVG GPU-image wrapper cache are correct. The fault is that an offscreen implementation layer is admitted into automatic frame composition.

## Goals

- Distinguish layers intended for automatic frame composition from layers used only to produce an offscreen image texture.
- Keep offscreen image layers fully usable by subsequent GPU-only texture sampling.
- Preserve automatic composition for the main 2D GUI, 3D scene, swap-chain, and offscreen scene layers.
- Make the distinction generic in the GPU/draw2d framework rather than specific to NanoVG or font previews.
- Preserve layer ordering and scoped restoration behavior.

## Non-Goals

- Changing font-preview caching or invalidation.
- Changing NanoVG image-wrapper caching.
- Filtering layers solely by `gpu::enum_output`.
- Removing offscreen layers from the device's layer array while their scoped rendering is active.
- Changing CPU sampling or offscreen 3D scene output behavior.

## Considered Approaches

### 1. Filter all `e_output_gpu_buffer` layers

This is rejected because `e_output_gpu_buffer` describes where a context renders, not whether its layer should participate in frame composition. The on-screen 3D scene legitimately renders to a GPU buffer and must still be merged into the final window image.

### 2. Remove image-rendering layers from the device layer array

This is rejected because the array also provides frame ordering, current-layer indexing, previous-layer lookup, completion tracking, and semaphore/fence relationships. Removing entries during a nested layer scope would make those responsibilities fragile.

### 3. Add explicit per-layer composition intent

This is the selected approach. Each layer records whether it should be included in automatic final-frame composition. The default remains enabled. Generic GPU-backed memory graphics mark only their image-rendering layers as excluded. The layer continues through its normal render and synchronization lifecycle and remains available for explicit texture sampling.

## Architecture

`gpu::layer` will gain a boolean composition-intent member named to express inclusion in automatic frame composition. It defaults to `true` and is reset to `true` every time `initialize_gpu_layer` prepares a reusable layer entry. Resetting during initialization prevents intent from leaking between frames or between pooled graphics/context uses.

`gpu::graphics` will set the current layer's composition intent to `false` when the graphics object is rendering into an associated `image::image`. This decision is captured on the layer after the layer has been created and before rendering proceeds. It is based on the semantic role of the graphics operation, not on the backend, context output type, or texture format.

Window graphics and graphics3d contexts do not opt out, so their layers retain the default `true` value.

## Frame Flow

For an on-demand font preview:

1. `text_box::update` acquires graphics for its image and opens a scoped layer.
2. The GPU device creates or reuses a `gpu::layer`, initially composited by default.
3. Generic `gpu::graphics` recognizes that it is drawing into an associated image and marks that layer as excluded from automatic composition.
4. NanoVG renders the text into the layer's GPU texture and completes the layer normally.
5. The font list samples that texture through the normal GPU-only image path at the intended destination rectangle.
6. When the window's closing layer performs final composition, it omits the image-rendering layer but retains the GUI and 3D scene layers.

The excluded layer is not destroyed early and is not removed from the device array. Only its participation in the final automatic merge changes.

## Composition Filtering

When `gpu::renderer::end_layer(true)` takes the device's frame layer snapshot, it will derive a second list containing only layers whose composition intent is enabled.

That filtered list must be used consistently for:

- waiting for layers required by the final merge;
- the `merge_layers` call;
- collecting layer signal semaphores that the merge command waits on.

Using one filtered list for all three operations prevents the compositor from waiting on or merging an excluded implementation layer accidentally. The full device layer array remains intact for layer lifecycle and diagnostics.

If no composited layers remain, the existing no-merge behavior applies.

## Backend Behavior

The composition flag belongs to `bred`'s generic GPU layer model. Backend `merge_layers` implementations continue receiving a layer array and require no backend-specific policy.

NanoVG is the first runtime path exercising the distinction, but the behavior applies equally to any GPU-backed draw2d implementation that renders an `image::image` through generic `gpu::graphics`.

## Failure Handling

The new flag introduces no new fallible operation. Its safe default is automatic composition.

If a graphics path does not explicitly identify itself as image-backed, behavior remains unchanged. Reused layers reset to the safe default before any compositor-specific override, preventing a prior memory-image operation from suppressing a later normal layer.

## Diagnostics

Existing performance and image-boundary diagnostics remain unchanged. If focused diagnostics are needed during runtime validation, they may report the layer index and composition intent, but permanent high-volume logging is not required for this fix.

## Testing

Implementation will be test-driven.

Focused contract tests will verify that:

- a newly initialized or reused `gpu::layer` defaults to automatic composition;
- generic image-backed GPU graphics opt their current layer out;
- non-image-backed graphics leave composition enabled;
- the closing renderer filters its snapshot before waiting, merging, and collecting merge semaphores;
- the device's complete layer array is not mutated by composition filtering;
- no output-type-wide `e_output_gpu_buffer` exclusion is introduced.

Existing graphics-lease, scoped-layer, GPU-context pool, NanoVG image lifecycle, and NanoVG wrapper-cache contracts must continue to pass. Debug x64 builds of the affected libraries and `shared_app_graphics3d_continuum` must succeed.

Runtime validation will confirm that:

- newly cached normal font previews no longer appear once at window position `(0,0)` while scrolling;
- the first large hover preview no longer appears once at `(0,0)`;
- both previews remain correctly rendered at their intended positions;
- the 2D GUI and 3D scene continue to compose correctly;
- font-list scrolling remains responsive and the preview cache remains GPU-only.
