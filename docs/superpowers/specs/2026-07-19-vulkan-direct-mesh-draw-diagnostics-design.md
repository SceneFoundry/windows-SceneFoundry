# Vulkan Direct Mesh Draw Diagnostics Design

## Purpose

Identify why Vulkan offscreen rendering repeatedly loses the device immediately before the Stone Sphere's 26,352-index draw. The latest crash dump confirms that the Wood Barrel draw completes, the Stone Sphere vertex and index buffers bind, and the Stone Sphere draw never starts.

## Current Gap

`gpu_vulkan::model_buffer::draw2` validates uploaded vertex/index buffer sizes and index ranges, but `gpu_vulkan::gltf::mesh::draw2` bypasses that method and calls `vkCmdDrawIndexed` directly. Consequently, the models involved in the deterministic crash do not emit the existing upload diagnostic.

## Approaches

1. **Instrument the direct mesh path (recommended).** Reuse `inspect_model_buffer_upload` immediately before the direct `vkCmdDrawIndexed`. Log buffer handles, byte sizes, counts, type sizes, maximum index, and validation booleans once per mesh. Throw before submission if the data is invalid. This preserves rendering when data is valid and gives direct evidence when it is not.
2. **Skip the Stone Sphere draw.** Temporarily suppress the 26,352-index draw and test whether device loss disappears or moves to another draw. This is strong bisection evidence but should follow validation because a hard-coded skip provides less information and changes scene behavior.
3. **Capture a full API trace.** Capture and replay every Vulkan call. This is heavier, may perturb timing, and is unlikely to add more immediate value than validating the exact buffers at the repeatable failure boundary.

## Selected Design

Add a diagnostic helper for direct mesh draws that consumes the existing CPU model data and the Vulkan model buffer's actual allocations. `gpu_vulkan::gltf::mesh::draw2` will call it after binding and before drawing.

For each mesh, the first draw logs:

- mesh/model/model-buffer addresses;
- Vulkan vertex and index buffer handles;
- vertex count, vertex stride, required vertex bytes, and allocated vertex bytes;
- index count, index element size, required index bytes, and allocated index bytes;
- maximum index and whether it is within the vertex range;
- whether the index element type is supported.

If validation fails, execution throws before `vkCmdDrawIndexed`, preventing invalid data from reaching the driver. Valid meshes continue unchanged.

The first runtime test will not skip any model. If all direct draws validate but the device still stops at the same checkpoint, a second isolated change will suppress the Stone Sphere draw for one run.

## Testing

- Extend the existing pure `inspect_model_buffer_upload` test with the Stone Sphere's observed counts and invalid boundary cases.
- Add a source-integration assertion proving `gpu_vulkan::gltf::mesh::draw2` invokes the diagnostic before `vkCmdDrawIndexed`.
- Verify the test fails before production integration and passes afterward.
- Compile `gpu_vulkan:ClCompile` for Debug x64 and run `git diff --check` plus CRLF checks.
- Runtime success for the diagnostic stage means each direct mesh reports a complete validation record before the previous device-loss point.

## Constraints

- Keep `gpu_vulkan::queue` and existing queue submission behavior unchanged.
- Do not change scene content or skip Stone Sphere in the first diagnostic run.
- Do not change public framework interfaces.
- Keep the main GPU context last in end-frame processing.
- Do not commit until runtime evidence is reviewed and the overall correction is ready.
