# Vulkan Direct Mesh Draw Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate and log the real Vulkan buffers used by the direct glTF mesh draw path before its indexed draw reaches the driver.

**Architecture:** Reuse the existing pure `inspect_model_buffer_upload` calculation in `gpu_vulkan::gltf::mesh::draw2`. The direct path will inspect the Vulkan model buffer's CPU model data and actual vertex/index allocations, log the complete record once per model buffer, and throw before `vkCmdDrawIndexed` when invalid.

**Tech Stack:** C++20, Vulkan 1.x, existing standalone assertion tests, Visual Studio/MSBuild.

## Global Constraints

- Do not skip Stone Sphere in this diagnostic run.
- Keep `gpu_vulkan::queue` and queue submission behavior unchanged.
- Do not change public framework interfaces or device post-frame ordering.
- Use CRLF line endings in modified C++ source and test files.
- Do not commit until runtime evidence is reviewed.

---

### Task 1: Cover and Instrument the Direct Mesh Draw

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/tests/model_buffer_upload_diagnostics_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/gltf/mesh.cpp`

**Interfaces:**
- Consumes: `inspect_model_buffer_upload`, `gpu_vulkan::model_buffer`, its `memory_buffer` allocations, and `model_data_base` counts/data.
- Produces: one `gpu_vulkan direct mesh upload diagnostic` record per model buffer and a pre-submit exception for invalid data.

- [ ] **Step 1: Add the failing regression coverage**

Extend the pure helper test with a synthetic valid Stone Sphere-sized data set: 4,394 vertices, 26,352 32-bit indexes, and a maximum index of 4,393. Add source integration checks that `gltf/mesh.cpp` calls `inspect_model_buffer_upload`, logs the direct-mesh diagnostic, checks `diagnostic.is_valid()`, and performs all of those operations before `vkCmdDrawIndexed`.

- [ ] **Step 2: Run the focused test and verify RED**

Compile the test with Visual Studio `cl`, direct output to `%TEMP%`, and run it from `source/app-graphics3d`.

Expected: the pure helper assertions pass, then the source integration assertion fails because `gltf/mesh.cpp` does not call `inspect_model_buffer_upload`.

- [ ] **Step 3: Add minimal direct-path validation and logging**

In `gpu_vulkan::gltf::mesh::draw2`, after `bind2` and before `vkCmdDrawIndexed`:

```cpp
::cast < ::gpu_vulkan::model_buffer > pmodelbuffer = m_pmodelbuffer;
::cast < ::gpu_vulkan::memory_buffer > pbufferVertex = pmodelbuffer->m_pbufferVertex;
::cast < ::gpu_vulkan::memory_buffer > pbufferIndex = pmodelbuffer->m_pbufferIndex;

auto blockIndexes = pmodelbuffer->m_pmodeldatabase2->index_data();
auto diagnostic = inspect_model_buffer_upload(
   pmodelbuffer->m_pmodeldatabase2->vertex_count(),
   pmodelbuffer->m_pmodeldatabase2->vertex_type_size(),
   pbufferVertex->m_pbuffer->m_size,
   pmodelbuffer->m_pmodeldatabase2->index_count(),
   pmodelbuffer->m_pmodeldatabase2->index_type_size(),
   pbufferIndex->m_pbuffer->m_size,
   blockIndexes.data());
```

Log mesh/model/model-buffer addresses, Vulkan buffer handles, all counts and byte sizes, maximum index, and validation booleans when `m_bUploadDiagnosticLogged` is false or validation fails. Set the existing model-buffer flag after logging. Throw `error_failed` before drawing when invalid.

- [ ] **Step 4: Run the focused test and verify GREEN**

Expected: the test exits `0` and creates no workspace compiler artifacts.

- [ ] **Step 5: Run static and build verification**

Normalize the two modified C++ files to CRLF. Run the focused test again, `git diff --check`, the bare-LF check, and `gpu_vulkan:ClCompile` for Debug x64.

Expected: focused test and build exit `0`; whitespace and line-ending checks report no errors. Existing compiler warnings may remain.

- [ ] **Step 6: Runtime handoff**

Run Vulkan offscreen in Visual Studio. Capture the `gpu_vulkan direct mesh upload diagnostic` lines through the first device loss or stable render period. Do not close an assertion message box before saving the diagnostic output.

---

### Task 2: Isolate the Stone Sphere Draw

**Files:**
- Create: `source/app-graphics3d/gpu_vulkan/direct_mesh_device_loss_probe.h`
- Modify: `source/app-graphics3d/gpu_vulkan/tests/model_buffer_upload_diagnostics_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/gltf/mesh.cpp`

**Interfaces:**
- Produces: `gpu_vulkan::direct_mesh_device_loss_probe_should_skip(std::size_t indexCount)`, returning true only for the observed Stone Sphere index count of 26,352.
- Consumes: the validated direct mesh index count immediately before `vkCmdDrawIndexed`.

- [ ] **Step 1: Add a failing predicate test**

Require the diagnostic predicate to skip 26,352 indexes while retaining the adjacent observed draws of 16,992 and 30,888 indexes. Add a source-integration assertion requiring the skip log and early return to appear after validation but before `vkCmdDrawIndexed`.

- [ ] **Step 2: Verify RED**

Compile and run the focused test from `source/app-graphics3d`.

Expected: compilation fails because `direct_mesh_device_loss_probe.h` does not exist.

- [ ] **Step 3: Implement the isolated probe**

Create the `constexpr` predicate and call it after successful upload validation. When true, log `gpu_vulkan direct mesh draw skipped for device loss probe` with mesh, model, model-buffer, and index-count fields, then return without recording `vkCmdDrawIndexed`.

- [ ] **Step 4: Verify GREEN and compile Vulkan**

Run the focused test, CRLF and diff checks, and `gpu_vulkan:ClCompile` for Debug x64.

Expected: test and compile exit `0`; no whitespace or line-ending errors.

- [ ] **Step 5: Runtime bisection handoff**

Run Vulkan offscreen through the previous nine-second failure window. If stable, the Stone Sphere draw itself triggers the Intel driver failure; if device loss moves to another draw, compare the new crash checkpoint.
