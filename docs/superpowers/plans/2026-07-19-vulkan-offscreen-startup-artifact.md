# Vulkan Offscreen Startup Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce decisive first-frame evidence for the Vulkan offscreen blue flash and correct the independently confirmed unbounded GPU-layer lifecycle before selecting the final artifact fix.

**Architecture:** Add a small, deterministic BGRA fingerprint helper at the Vulkan CPU-readback boundary and log only the first twelve samples. Reset the generic device layer stack once at the start of each top-level frame so layers remain ordered within a frame but are reused across frames. Stop at a runtime evidence checkpoint; the final artifact behavior change must be planned from the captured sample data rather than guessed.

**Tech Stack:** C++20, Vulkan 1.4, SceneFoundry GPU framework, MSVC/Visual Studio 2022, Debug x64.

## Global Constraints

- Preserve Windows CRLF line endings in modified C++ and project files.
- Keep `gpu_vulkan::queue` as the Vulkan queue wrapper.
- Keep `m_pgpucontextMain` last in post-frame context dispatch.
- Do not change skybox orientation or shader coordinate conventions.
- Do not permanently discard a fixed number of startup samples.
- Do not commit intermediate work; commit the validated complete change set only at the end.
- Preserve OpenGL, DirectX 11, DirectX 12, swap-chain rendering, CPU-buffer rendering, and runtime-adjustable offscreen FPS.

---

## File Structure

- Create `source/app-graphics3d/gpu_vulkan/cpu_sample_fingerprint.h`: dependency-free BGRA sample statistics used only by temporary diagnostics.
- Create `source/app-graphics3d/gpu_vulkan/tests/cpu_sample_fingerprint_test.cpp`: deterministic unit test for the fingerprint calculation.
- Create `source/app-graphics3d/gpu_vulkan/tests/cpu_sample_fingerprint_integration_test.cpp`: source-level guard that keeps temporary fingerprinting at the mapped readback boundary.
- Modify `source/app-graphics3d/gpu_vulkan/renderer.cpp`: log the first twelve mapped CPU samples without changing published pixels.
- Modify `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj`: compile the helper header as part of the Vulkan project.
- Modify `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj.filters`: place the helper in the existing header filter.
- Create `source/app/bred/gpu/tests/device_frame_layer_reset_test.cpp`: source-level regression test for frame/layer ordering.
- Modify `source/app/bred/gpu/device.cpp`: reset the layer stack at top-level frame start.

### Task 1: First-sample BGRA fingerprint

**Files:**
- Create: `source/app-graphics3d/gpu_vulkan/cpu_sample_fingerprint.h`
- Create: `source/app-graphics3d/gpu_vulkan/tests/cpu_sample_fingerprint_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj`
- Modify: `source/app-graphics3d/gpu_vulkan/gpu_vulkan.vcxproj.filters`

**Interfaces:**
- Consumes: tightly packed or explicitly-strided BGRA8 pixels after Vulkan readback mapping.
- Produces: `gpu_vulkan::cpu_sample_fingerprint calculate_cpu_sample_fingerprint(const void *, int, int, int)`.

- [ ] **Step 1: Write the failing unit test**

Create a test with a two-pixel BGRA row: opaque blue `(255,0,0,255)` followed by opaque red `(0,0,255,255)`. Require a pixel count of 2, blue-dominant count of 1, channel sums of 255 for blue and red, green sum of 0, alpha sum of 510, and a nonzero FNV-1a hash.

```cpp
#include "../cpu_sample_fingerprint.h"
#include <cassert>
#include <cstdint>

int main()
{
   const std::uint8_t pixels[] = {
      255, 0, 0, 255,
      0, 0, 255, 255};

   const auto result = gpu_vulkan::calculate_cpu_sample_fingerprint(
      pixels, 2, 1, 8);

   assert(result.m_uPixelCount == 2);
   assert(result.m_uBlueDominantPixelCount == 1);
   assert(result.m_uBlueSum == 255);
   assert(result.m_uGreenSum == 0);
   assert(result.m_uRedSum == 255);
   assert(result.m_uAlphaSum == 510);
   assert(result.m_uHash != 0);
   return 0;
}
```

- [ ] **Step 2: Run the test and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d` in a Visual Studio x64 Native Tools prompt:

```powershell
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_sample_fingerprint_test.cpp /Fe:cpu_sample_fingerprint_test.exe
```

Expected: compilation fails because `gpu_vulkan/cpu_sample_fingerprint.h` does not exist.

- [ ] **Step 3: Implement the dependency-free helper**

Create a header containing a plain result struct and inline function. Hash every pixel byte in display order with 64-bit FNV-1a. Count a pixel as blue-dominant only when `blue > red` and `blue > green`.

```cpp
#pragma once
#include <cstdint>

namespace gpu_vulkan
{
   struct cpu_sample_fingerprint
   {
      std::uint64_t m_uHash{};
      std::uint64_t m_uPixelCount{};
      std::uint64_t m_uBlueDominantPixelCount{};
      std::uint64_t m_uBlueSum{};
      std::uint64_t m_uGreenSum{};
      std::uint64_t m_uRedSum{};
      std::uint64_t m_uAlphaSum{};
   };

   inline cpu_sample_fingerprint calculate_cpu_sample_fingerprint(
      const void *pData, int width, int height, int stride)
   {
      cpu_sample_fingerprint result;
      result.m_uHash = 14695981039346656037ULL;
      const auto *bytes = static_cast<const std::uint8_t *>(pData);

      for (int y = 0; y < height; ++y)
      {
         const auto *row = bytes + y * stride;
         for (int x = 0; x < width; ++x)
         {
            const auto *pixel = row + x * 4;
            const auto blue = pixel[0];
            const auto green = pixel[1];
            const auto red = pixel[2];
            const auto alpha = pixel[3];
            result.m_uBlueSum += blue;
            result.m_uGreenSum += green;
            result.m_uRedSum += red;
            result.m_uAlphaSum += alpha;
            result.m_uBlueDominantPixelCount += blue > red && blue > green;
            ++result.m_uPixelCount;
            for (int channel = 0; channel < 4; ++channel)
            {
               result.m_uHash ^= pixel[channel];
               result.m_uHash *= 1099511628211ULL;
            }
         }
      }
      return result;
   }
}
```

Add the header to the same `ClInclude` item group and filter used by the other `gpu_vulkan` diagnostic helper headers.

- [ ] **Step 4: Run the test and verify GREEN**

```powershell
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_sample_fingerprint_test.cpp /Fe:cpu_sample_fingerprint_test.exe
.\cpu_sample_fingerprint_test.exe
```

Expected: compilation succeeds and the executable exits with code 0.

### Task 2: Log the first twelve published Vulkan samples

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp` in `renderer::cpu_buffer_sampler::send_sample`.
- Create: `source/app-graphics3d/gpu_vulkan/tests/cpu_sample_fingerprint_integration_test.cpp`

**Interfaces:**
- Consumes: `calculate_cpu_sample_fingerprint` from Task 1 and existing `m_uSampleSerial`.
- Produces: one `gpu_vulkan cpu sample pixels:` information line for sample serials 1 through 12.

- [ ] **Step 1: Write the failing readback-boundary integration test**

Create a source-level test that extracts `renderer::cpu_buffer_sampler::send_sample` from `renderer.cpp` and requires all of the following in order: successful `vkMapMemory`, `calculate_cpu_sample_fingerprint`, the `gpu_vulkan cpu sample pixels:` log text, `pcpubuffer->set_pixels`, and `vkUnmapMemory`. It must also require `m_uSampleSerial <= 12` and reject any `return` between fingerprint calculation and `set_pixels`.

- [ ] **Step 2: Run the unit test and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d`:

```powershell
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_sample_fingerprint_integration_test.cpp /Fe:cpu_sample_fingerprint_integration_test.exe
.\cpu_sample_fingerprint_integration_test.exe
```

Expected: assertion failure because `send_sample` does not yet calculate or log a fingerprint.

- [ ] **Step 3: Add temporary mapped-buffer diagnostics**

Include `cpu_sample_fingerprint.h` from `renderer.cpp`. Immediately after successful `vkMapMemory`, and before `pcpubuffer->set_pixels`, calculate the fingerprint when `m_uSampleSerial <= 12` and log:

```cpp
if (m_uSampleSerial <= 12)
{
   const auto fingerprint = calculate_cpu_sample_fingerprint(
      pData, iWidth, iHeight, iWidth * 4);
   information(
      "gpu_vulkan cpu sample pixels: serial={} frame={} hash={} pixels={} "
      "blue_dominant={} blue_sum={} green_sum={} red_sum={} alpha_sum={}",
      (unsigned long long)m_uSampleSerial,
      m_pcontext->m_pgpudevice->get_frame_index3(),
      (unsigned long long)fingerprint.m_uHash,
      (unsigned long long)fingerprint.m_uPixelCount,
      (unsigned long long)fingerprint.m_uBlueDominantPixelCount,
      (unsigned long long)fingerprint.m_uBlueSum,
      (unsigned long long)fingerprint.m_uGreenSum,
      (unsigned long long)fingerprint.m_uRedSum,
      (unsigned long long)fingerprint.m_uAlphaSum);
}
```

Do not modify the pointer, dimensions, stride, Y-swap flag, callback, or pixels passed to `set_pixels`.

- [ ] **Step 4: Run the unit test and existing sampling tests**

Compile and run:

```powershell
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_sample_fingerprint_test.cpp /Fe:cpu_sample_fingerprint_test.exe
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_sample_fingerprint_integration_test.cpp /Fe:cpu_sample_fingerprint_integration_test.exe
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_buffer_sampling_extent_test.cpp /Fe:cpu_buffer_sampling_extent_test.exe
cl /nologo /std:c++20 /EHsc gpu_vulkan\tests\cpu_buffer_sampling_sync_test.cpp /Fe:cpu_buffer_sampling_sync_test.exe
.\cpu_sample_fingerprint_test.exe
.\cpu_sample_fingerprint_integration_test.exe
.\cpu_buffer_sampling_extent_test.exe
.\cpu_buffer_sampling_sync_test.exe
```

Expected: all executables exit with code 0.

### Task 3: Reset the device layer stack at frame start

**Files:**
- Create: `source/app/bred/gpu/tests/device_frame_layer_reset_test.cpp`
- Modify: `source/app/bred/gpu/device.cpp:1053`

**Interfaces:**
- Consumes: existing `gpu::device::start_stacking_layers()` and `gpu::device::start_frame()`.
- Produces: each top-level device frame starts with `m_iLayerCount == 0`; layer creation within that frame remains ordered from zero upward.

- [ ] **Step 1: Write a failing source-order regression test**

The test reads `gpu/device.cpp`, extracts `device::start_frame`, and requires `start_stacking_layers();` after the post-frame registry clear and before `m_pgpucontextMain->on_new_frame();`.

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>

int main()
{
   std::ifstream stream("gpu/device.cpp", std::ios::binary);
   const std::string source{
      std::istreambuf_iterator<char>(stream),
      std::istreambuf_iterator<char>()};
   const auto start = source.find("void device::start_frame()");
   const auto end = source.find("void device::end_frame()", start);
   assert(start != std::string::npos && end != std::string::npos);
   const auto body = source.substr(start, end - start);
   const auto clear = body.find("m_postframecontextregistry.clear();");
   const auto reset = body.find("start_stacking_layers();");
   const auto newFrame = body.find("m_pgpucontextMain->on_new_frame();");
   assert(clear < reset && reset < newFrame);
   return 0;
}
```

- [ ] **Step 2: Run the test and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app`:

```powershell
cl /nologo /std:c++20 /EHsc bred\gpu\tests\device_frame_layer_reset_test.cpp /Fe:device_frame_layer_reset_test.exe
.\device_frame_layer_reset_test.exe
```

Expected: assertion failure because `start_frame()` does not reset the layer stack.

- [ ] **Step 3: Add the minimal lifecycle correction**

In `device::start_frame()`, after releasing the synchronization lock used to clear `m_postframecontextregistry` and before incrementing `m_iFrameSerial2`, add:

```cpp
start_stacking_layers();
```

Do not move or alter post-frame dispatch, context registration, or main-context-last behavior.

- [ ] **Step 4: Run the test and verify GREEN**

Run the Step 2 commands. Expected: executable exits with code 0.

### Task 4: Build and runtime evidence checkpoint

**Files:**
- Verify: `solution-windows/SceneFoundry.sln`
- Inspect runtime log supplied from `shared_app_graphics3d_continuum.exe`.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a table for sample serials 1-12 containing frame index, layer index, texture identity, extent, hash, and blue-dominant ratio.

- [ ] **Step 1: Build the Debug x64 Vulkan target**

```powershell
msbuild solution-windows\SceneFoundry.sln /t:graphics3d_vulkan /p:Configuration=Debug /p:Platform=x64 /m /nologo /v:minimal
```

Expected: build succeeds with zero errors.

- [ ] **Step 2: Run the existing Vulkan regression probes**

From `source/app-graphics3d`, compile and run `cpu_buffer_sampling_device_loss_probe_test.cpp`, `cpu_buffer_sampling_extent_test.cpp`, `cpu_buffer_sampling_sync_test.cpp`, and `global_ubo_descriptor_and_light_count_test.cpp` using the same MSVC flags as Tasks 1-2.

Expected: all exit with code 0.

- [ ] **Step 3: Runtime-test Vulkan offscreen startup**

Run `shared_app_graphics3d_continuum` under Visual Studio with Vulkan, swap chain disabled, and GDI+ GUI rendering. Keep validation-layer breaks enabled. Observe whether the blue artifact appears and retain the Output window log through at least sample serial 12.

Expected structural evidence after the layer reset: all twelve `gpu_vulkan cpu sample source:` lines report `layer_index=0`; frame indices continue cycling `1,2,0`; extents remain equal.

- [ ] **Step 4: Classify the first bad sample without changing behavior**

Build a comparison table from the `cpu sample source` and `cpu sample pixels` lines. Mark the earliest fingerprint whose blue-dominant ratio or channel totals differ sharply from samples 4-12. If the artifact remains but the first twelve fingerprints do not contain an outlier, capture the GUI presentation timing before adding more GPU changes; that result places the bug after `set_pixels`.

This is a mandatory checkpoint. Do not implement UBO changes, sample dropping, or further synchronization changes until the captured evidence identifies whether the outlier is in GPU readback or GUI presentation.

### Task 5: Review checkpoint and next-plan update

**Files:**
- Modify: `docs/superpowers/plans/2026-07-19-vulkan-offscreen-startup-artifact.md`

**Interfaces:**
- Consumes: the runtime comparison table from Task 4.
- Produces: an exact TDD task for the confirmed final boundary, replacing speculation with observed serial/resource data.

- [ ] **Step 1: Record the evidence**

Append the twelve-sample comparison table and the observed artifact timing to this plan.

- [ ] **Step 2: Add the exact final regression and production edit**

If the GPU fingerprint contains the outlier, specify the exact UBO, layer texture, or render-completion resource whose identity differs and add a focused failing test for that resource selection. If all GPU fingerprints are stable, specify the exact image-target/GUI presentation transition that displayed the artifact and add its focused failing test instead.

- [ ] **Step 3: Obtain review before the final behavior change**

Present the recorded evidence and exact final task for approval. The implementation phase resumes only after that review, preventing a fixed-frame warm-up workaround from being introduced without proof.

## Runtime Evidence: 2026-07-19

The layer reset behaved as intended: every sampled frame used `layer_index=0`,
while Vulkan frame indices cycled `1, 2, 0`. All selected and frame-target
textures remained `1270x643`.

| Sample | Frame | Selected texture | Hash | Blue-dominant pixels | Result |
|---:|---:|---:|---:|---:|---|
| 1 | 1 | 2276089524416 | 13157192872851738360 | 747736 | saturated blue artifact |
| 2 | 2 | 2276089503936 | 13157192872851738360 | 747736 | saturated blue artifact |
| 3 | 0 | 2276089483456 | 2244726679779611479 | 143301 | correct stable scene |
| 4 | 1 | 2276089524416 | 2244726679779611479 | 143301 | correct stable scene |
| 5 | 2 | 2276089503936 | 2244726679779611479 | 143301 | correct stable scene |
| 6-12 | 0,1,2 | same three textures | 2244726679779611479 | 143301 | correct stable scene |

The exact transition at the first use of frame 0 matches the command-buffer
code. `gpu::block::update_frame` uploads the global UBO selected by
`device::get_frame_index3()`, and Vulkan descriptor binding selects a UBO using
`command_buffer::m_iCommandBufferFrameIndex2`. Non-layer renderer command
buffers assign that field, but both `gpu::layer::getCurrentCommandBuffer4` and
`gpu_vulkan::layer::getCurrentCommandBuffer4` return layered command buffers
without assigning it. The constructor also leaves the field uninitialized.

The observed value behaved as frame index 0. Samples 1 and 2 therefore updated
UBOs 1 and 2 while rendering through the initially empty UBO 0. Sample 3
populated UBO 0, after which all samples rendered correctly even when frame
indices 1 and 2 were reused.

The temporary fingerprint calculation also explains the longer visible
artifact: in Debug it scans 816,610 pixels and added approximately 0.65 seconds
to each of the first sampled frames.

### Task 6: Assign the layered command-buffer frame index

**Files:**
- Modify: `source/app/bred/gpu/command_buffer.cpp`
- Modify: `source/app/bred/gpu/layer.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/layer.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/tests/global_ubo_descriptor_and_light_count_test.cpp`

**Interfaces:**
- Consumes: `gpu::device::get_frame_index3()` and the existing command-buffer
  fields `m_iCommandBufferFrameIndex2` and `m_iCommandBufferImageIndex`.
- Produces: every layered command buffer identifies the current frame before
  descriptor selection.

- [x] **Step 1: Extend the regression test and verify RED**

Extend `global_ubo_descriptor_and_light_count_test.cpp` to require:

```cpp
const auto commandBufferImplementation = read_text_file("../app/bred/gpu/command_buffer.cpp");
const auto genericLayerImplementation = read_text_file("../app/bred/gpu/layer.cpp");
const auto vulkanLayerImplementation = read_text_file("gpu_vulkan/layer.cpp");

assert(commandBufferImplementation.find("m_iCommandBufferFrameIndex2 = -1;") != std::string::npos);
assert(genericLayerImplementation.find("pcommandbufferLayer->m_iCommandBufferFrameIndex2 = iFrameIndex;") != std::string::npos);
assert(vulkanLayerImplementation.find("pcommandbufferLayer->m_iCommandBufferFrameIndex2 = iFrameIndex;") != std::string::npos);
```

Compile and run from `source/app-graphics3d`. Expected: assertion failure
because none of these three assignments currently exists.

- [x] **Step 2: Initialize the frame field defensively**

In `gpu::command_buffer::command_buffer()`, immediately before initializing the
image index, add:

```cpp
m_iCommandBufferFrameIndex2 = -1;
```

This converts any future missing assignment from undefined descriptor
selection into the existing invalid-frame-index error path.

- [x] **Step 3: Assign frame and image indices in the generic layer path**

In `gpu::layer::getCurrentCommandBuffer4`, obtain the current device frame
index separately from the image index and assign both fields before returning:

```cpp
const auto iFrameIndex =
   m_pgpurenderer->m_pgpucontext->m_pgpudevice->get_frame_index3();
pcommandbufferLayer->m_iCommandBufferFrameIndex2 = iFrameIndex;
pcommandbufferLayer->m_iCommandBufferImageIndex = iImageIndex;
```

- [x] **Step 4: Assign frame and image indices in the Vulkan override**

In `gpu_vulkan::layer::getCurrentCommandBuffer4`, after selecting the command
buffer with `iFrameIndex`, add:

```cpp
pcommandbufferLayer->m_iCommandBufferFrameIndex2 = iFrameIndex;
pcommandbufferLayer->m_iCommandBufferImageIndex = iFrameIndex;
```

- [x] **Step 5: Verify GREEN and build**

Compile and run the extended global-UBO test plus all CPU sampling regression
tests. Build `graphics3d_vulkan` from `SceneFoundry.sln` in Debug x64. Expected:
all tests and the build pass.

- [x] **Step 6: Runtime verify, then remove temporary fingerprints**

Run Vulkan offscreen rendering. Expected: sample 1 is already the correct
scene; samples 1-12 do not show the saturated-blue fingerprint. After runtime
confirmation, remove `cpu_sample_fingerprint.h`, its two tests, project entries,
and the `cpu sample pixels` logging block. Keep the layer-stack reset and its
regression test.
