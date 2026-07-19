# Vulkan Offscreen Buffer Readback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Vulkan offscreen CPU sampling's device-losing linear-image destination with a host-visible transfer-destination buffer.

**Architecture:** `gpu_vulkan::renderer::cpu_buffer_sampler` will keep one `gpu_vulkan::buffer` per frame index. Sampling transitions the rendered source image, copies it with `vkCmdCopyImageToBuffer`, applies transfer-to-host visibility, then maps the buffer and feeds the unchanged framework CPU buffer.

**Tech Stack:** C++20, Vulkan 1.x, Visual Studio/MSBuild, existing `gpu_vulkan::queue`, `command_buffer`, `context`, and `buffer` wrappers.

## Global Constraints

- Preserve the public `gpu::renderer`, `gpu::context`, device post-frame, and CPU-buffer interfaces.
- Retain the `gpu_vulkan::queue` wrapper for every queue operation.
- Keep the main GPU context last in device post-frame ordering.
- Use CRLF line endings for modified C++ and test files.
- Do not retain a fallback to the known device-losing linear-image readback path.
- Do not make intermediate commits; create one final commit only after implementation and verification.

---

### Task 1: Lock the Buffer-Readback Contract with a Failing Test

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/tests/cpu_buffer_sampling_device_loss_probe_test.cpp`
- Test: `source/app-graphics3d/gpu_vulkan/tests/cpu_buffer_sampling_device_loss_probe_test.cpp`

**Interfaces:**
- Consumes: the existing source-scanning regression-test structure.
- Produces: a failing contract requiring buffer allocation, image-to-buffer copy, host visibility, and tightly packed CPU pixels while rejecting active linear-image readback operations.

- [ ] **Step 1: Update the expected sampler stages**

Replace the destination-image stages with the buffer stages:

```cpp
const auto sourceTransition = rendererImplementation.find("cpu_sample_stage_source_transition");
const auto bufferCopy = rendererImplementation.find("cpu_sample_stage_buffer_copy");
const auto hostVisibility = rendererImplementation.find("cpu_sample_stage_host_visibility");

if (sourceTransition == std::string::npos
   || bufferCopy == std::string::npos
   || hostVisibility == std::string::npos
   || !(sourceTransition < bufferCopy && bufferCopy < hostVisibility))
{
   return 1;
}
```

- [ ] **Step 2: Require the buffer-readback primitives**

Add assertions that the sampler implementation contains:

```cpp
const auto sampleImplementation =
   rendererImplementation.substr(sampleBegin, sampleEnd - sampleBegin);

if (rendererHeader.find("::pointer_array < buffer >") == std::string::npos
   || rendererImplementation.find("VK_BUFFER_USAGE_TRANSFER_DST_BIT") == std::string::npos
   || rendererImplementation.find("VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT") == std::string::npos
   || rendererImplementation.find("VK_MEMORY_PROPERTY_HOST_COHERENT_BIT") == std::string::npos
   || !contains_uncommented_call(sampleImplementation, "vkCmdCopyImageToBuffer(")
   || !contains_uncommented_call(sampleImplementation, "vkCmdPipelineBarrier("))
{
   return 1;
}
```

Reject the old readback calls and require a packed scan:

```cpp
if (contains_uncommented_call(sampleImplementation, "vkCmdCopyImage(")
   || contains_uncommented_call(sampleImplementation, "vkCmdClearColorImage(")
   || rendererImplementation.find("iWidth * 4") == std::string::npos)
{
   return 1;
}
```

- [ ] **Step 3: Run the focused test and verify RED**

Compile the test with Visual Studio's `cl`, directing `.obj` and `.exe` files to `%TEMP%`, then run it from `source/app-graphics3d`.

Expected: exit code `1`, because the production sampler still owns linear textures and calls `vkCmdCopyImage`.

---

### Task 2: Replace Per-Frame Linear Images with Readback Buffers

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.h:26-60`
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp:750-868`
- Test: `source/app-graphics3d/gpu_vulkan/tests/cpu_buffer_sampling_device_loss_probe_test.cpp`

**Interfaces:**
- Consumes: `context::create_buffer(VkDeviceSize, VkBufferUsageFlags, VkMemoryPropertyFlags)`.
- Produces: `cpu_buffer_sampler::m_buffera`, one correctly sized host-visible buffer per frame index.

- [ ] **Step 1: Change sampler ownership**

In `renderer.h`, replace:

```cpp
::pointer_array < texture > m_texturea;
```

with:

```cpp
::pointer_array < buffer > m_buffera;
```

- [ ] **Step 2: Update clear and resize allocation**

Make `clear()` release `m_buffera`. In `update`, calculate the exact packed size and reuse a matching buffer:

```cpp
const VkDeviceSize sizeReadback =
   static_cast<VkDeviceSize>(size.width())
   * static_cast<VkDeviceSize>(size.height())
   * 4;

auto & pbuffer = m_buffera.element_at_grow(
   pgpurendertarget->m_pgpurenderer->m_pgpucontext->m_pgpudevice->get_frame_index3());

if (pbuffer && pbuffer->m_size == sizeReadback)
{
   return;
}

pbuffer.release();

if (size.is_empty())
{
   return;
}

pbuffer = m_pcontext->create_buffer(
   sizeReadback,
   VK_BUFFER_USAGE_TRANSFER_DST_BIT,
   VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
```

- [ ] **Step 3: Compile the focused test**

Expected: the test remains RED because sampling still references the old image destination.

---

### Task 3: Record Image-to-Buffer Copy and Host Visibility

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp:887-1221`
- Test: `source/app-graphics3d/gpu_vulkan/tests/cpu_buffer_sampling_device_loss_probe_test.cpp`

**Interfaces:**
- Consumes: the current render-source `gpu_vulkan::texture`, per-frame `gpu_vulkan::buffer`, graphics queue wrapper, and managed single-time command completion.
- Produces: completed GPU copy into packed host-visible memory with stage annotations `source_transition`, `buffer_copy`, and `host_visibility`.

- [ ] **Step 1: Select and validate the destination buffer**

Replace the per-frame texture lookup with:

```cpp
auto & pbufferRef = m_buffera.element_at_grow(iFrameIndex);

if (!pbufferRef)
{
   return;
}
```

Update the diagnostic log to report the buffer handle and byte size instead of destination image format/layout state.

- [ ] **Step 2: Keep the successful source transition submission**

Retain the source `_set_state` call and annotation:

```cpp
pcommandbuffer->m_strAnnotation.formatf(
   "cpu_sample_serial=%llu cpu_sample_stage_source_transition",
   (unsigned long long)uSampleSerial);
```

The optional render-finished semaphore remains attached only to this first submission.

- [ ] **Step 3: Replace the image copy with a packed image-to-buffer copy**

Record a new annotated command buffer:

```cpp
pcommandbuffer->m_strAnnotation.formatf(
   "cpu_sample_serial=%llu cpu_sample_stage_buffer_copy",
   (unsigned long long)uSampleSerial);

VkBufferImageCopy copyRegion{};
copyRegion.bufferOffset = 0;
copyRegion.bufferRowLength = 0;
copyRegion.bufferImageHeight = 0;
copyRegion.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
copyRegion.imageSubresource.mipLevel = 0;
copyRegion.imageSubresource.baseArrayLayer = 0;
copyRegion.imageSubresource.layerCount = 1;
copyRegion.imageOffset = {0, 0, 0};
copyRegion.imageExtent = {
   static_cast<uint32_t>(ptexture->rectangle().width()),
   static_cast<uint32_t>(ptexture->rectangle().height()),
   1};

vkCmdCopyImageToBuffer(
   pcommandbuffer->m_vkcommandbuffer,
   ptexture->m_vkimage,
   ptexture->m_state2a.mip_layer_state(0, 0).m_vkimagelayout,
   pbufferRef->m_vkbuffer,
   1,
   &copyRegion);
```

Submit and fence-complete this command through `endSingleTimeCommands`.

- [ ] **Step 4: Add explicit transfer-to-host visibility**

Record a final annotated buffer barrier:

```cpp
pcommandbuffer->m_strAnnotation.formatf(
   "cpu_sample_serial=%llu cpu_sample_stage_host_visibility",
   (unsigned long long)uSampleSerial);

VkBufferMemoryBarrier barrier{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
barrier.buffer = pbufferRef->m_vkbuffer;
barrier.offset = 0;
barrier.size = VK_WHOLE_SIZE;

vkCmdPipelineBarrier(
   pcommandbuffer->m_vkcommandbuffer,
   VK_PIPELINE_STAGE_TRANSFER_BIT,
   VK_PIPELINE_STAGE_HOST_BIT,
   0,
   0, nullptr,
   1, &barrier,
   0, nullptr);
```

Submit and fence-complete this command through the existing queue wrapper.

- [ ] **Step 5: Remove the obsolete destination-image code**

Delete active destination image transitions, `VkImageCopy`, `vkCmdCopyImage`, destination host-layout transition, and their obsolete state/log variables. Do not modify unrelated texture or render-target state handling.

- [ ] **Step 6: Run the focused test**

Expected: the resource and copy assertions pass; the test may remain RED until CPU mapping is converted.

---

### Task 4: Map the Readback Buffer into the Existing CPU Buffer

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp:1296-1380`
- Test: `source/app-graphics3d/gpu_vulkan/tests/cpu_buffer_sampling_device_loss_probe_test.cpp`

**Interfaces:**
- Consumes: the fence-completed per-frame host-coherent buffer.
- Produces: the unchanged framework `gpu::cpu_buffer` contents used by GDI+.

- [ ] **Step 1: Replace image mapping with buffer mapping**

Use the context dimensions and packed scan:

```cpp
auto & pbufferRef = m_buffera.element_at_grow(
   pgpurendertarget->m_pgpurenderer->m_pgpucontext->m_pgpudevice->get_frame_index3());

if (!pbufferRef)
{
   return;
}

const int iWidth = m_pcontext->m_rectangle.width();
const int iHeight = m_pcontext->m_rectangle.height();
void * pData = nullptr;

VkCheckResult(vkMapMemory(
   m_pcontext->logicalDevice(),
   pbufferRef->m_vkdevicememory,
   0,
   pbufferRef->m_size,
   0,
   &pData));

m_pcontext->m_pcpubuffer->set_pixels(
   pData,
   iWidth,
   iHeight,
   iWidth * 4,
   false);

vkUnmapMemory(m_pcontext->logicalDevice(), pbufferRef->m_vkdevicememory);
```

Host-coherent allocation makes explicit invalidation unnecessary after the completed transfer and host visibility dependency.

- [ ] **Step 2: Remove obsolete linear-image mapping**

Delete `VkImageSubresource`, `vkGetImageSubresourceLayout`, image-memory mapping, `subResourceLayout.offset`, and `subResourceLayout.rowPitch` from `send_sample`.

- [ ] **Step 3: Run the focused test and verify GREEN**

Expected: exit code `0`.

---

### Task 5: Static Verification and Runtime Handoff

**Files:**
- Verify: `source/app-graphics3d/gpu_vulkan/renderer.h`
- Verify: `source/app-graphics3d/gpu_vulkan/renderer.cpp`
- Verify: `source/app-graphics3d/gpu_vulkan/tests/*.cpp`

**Interfaces:**
- Consumes: completed buffer-readback implementation.
- Produces: a buildable diagnostic binary ready for Visual Studio runtime verification.

- [ ] **Step 1: Normalize modified files to CRLF**

Run `unix2dos` on the modified C++ and test files.

- [ ] **Step 2: Run all focused tests**

Compile and run:

```text
command_buffer_fence_ownership_test
cpu_buffer_sampling_device_loss_probe_test
cpu_buffer_sampling_sync_test
queue_host_call_coverage_test
queue_host_call_diagnostics_test
```

Direct all compiler artifacts to `%TEMP%`.

Expected: five passes and no workspace `.obj` files.

- [ ] **Step 3: Compile the Vulkan project**

Run:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
& $msbuild 'solution-windows\SceneFoundry.sln' '/t:gpu_vulkan:ClCompile' '/p:Configuration=Debug' '/p:Platform=x64' '/m' '/v:minimal' '/nologo'
```

Expected: exit code `0`; pre-existing warnings may remain.

- [ ] **Step 4: Check diff and line endings**

Run `git -C source/app-graphics3d diff --check` and verify zero bare LF line endings in touched C++ files.

- [ ] **Step 5: Ask for Visual Studio runtime verification**

Expected successful stage sequence:

```text
cpu_sample_stage_source_transition
cpu_sample_stage_buffer_copy
cpu_sample_stage_host_visibility
```

Success criteria: no `VK_ERROR_DEVICE_LOST`, the offscreen 3D scene appears in the GDI+ window hierarchy, and repeated frames remain stable.

---

### Task 6: Final Verification and Commit

**Files:**
- Verify all modified files in the root repository and `source/app-graphics3d` submodule.

**Interfaces:**
- Consumes: user-confirmed successful runtime result.
- Produces: one intentional final commit containing the completed Vulkan readback correction and its diagnostics/tests.

- [ ] **Step 1: Re-run the focused tests and Vulkan compile after runtime confirmation**

Expected: all focused tests pass and `gpu_vulkan:ClCompile` exits `0`.

- [ ] **Step 2: Review final diffs without disturbing unrelated user changes**

Stage only files belonging to this Vulkan CPU-sampling investigation. Do not stage unrelated dirty-worktree files.

- [ ] **Step 3: Create one final commit**

Use a commit message describing Vulkan offscreen buffer readback, for example:

```text
fix(vulkan): read offscreen frames through host buffer
```
