# VKVG Direct Composed-Layer Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `draw2d_vkvg` directly into the ca2 Vulkan layer texture whenever `m_bIncludeInFrameComposition` is true, so `merge_layers()` samples the exact `VkImage` containing the 2D drawing.

**Architecture:** Have ca2 fabricate and own a `VkhImage` for each composed layer `VkImage`, pass it to the existing `vkvg_surface_create_for_VkhImage()` API, add a generic external-layer lifecycle that bypasses ca2's competing render pass, and cache one `VkhImage`/`VkvgSurface`/`VkvgContext` set per rotating composed-layer texture. Keep queue submissions on the existing shared Vulkan graphics queue and synchronize ca2's tracked image state at the vkvg handoff boundaries.

**Tech Stack:** C++17, C11, Vulkan 1.4, vkvg/VkhImage, ca2 `bred/gpu`, `gpu_vulkan`, CMake contract tests, standalone C++ source-contract tests, MSBuild Debug x64.

## Global Constraints

- Apply the direct target path only when `pgpulayer != nullptr` and `pgpulayer->m_bIncludeInFrameComposition == true`.
- Leave the existing vkvg-owned surface path present; do not refactor, extend, or add tests for the false case.
- Do not use `set_target_image()` for this integration.
- Do not restore `layer_end_copy()`.
- Do not add an intermediate image copy or CPU readback.
- Do not modify `merge_layers()` or its shaders.
- Require `VK_FORMAT_B8G8R8A8_UNORM`, one mip level, one image layer, `VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT`, and `VK_IMAGE_USAGE_SAMPLED_BIT` for the direct target.
- Keep vkvg and composition on the same Vulkan logical device, graphics queue family, and graphics queue.
- Keep the existing queue host-call mutex locked across vkvg preparation, drawing, flush, and ca2 handoff.
- Do not modify the pinned `port/graphics3d/vkvg/vkvg` submodule or vkvg/Vkh source patches. The only permitted wrapper change is exporting `vkh_image_import`, `vkh_image_status`, `vkh_image_create_view`, and `vkh_image_destroy` from the existing Windows `vkvg.def`.
- Preserve existing unrelated worktree changes.
- Use CRLF for modified and new C/C++ source and header files. Keep CMake files and unified patch files LF.
- Do not stage or commit unless the user explicitly authorizes Git mutations.

---

## File Structure

### VkhImage adapter boundary

- `source/app-graphics3d/draw2d_vkvg/graphics.h`: stores the ca2-owned imported `VkhImage` beside its surface and context.
- `source/app-graphics3d/draw2d_vkvg/graphics.cpp`: imports the exact ca2 `VkImage` through a stable `VkhDevice` view, creates its color view, passes it to the existing vkvg API, and destroys the wrapper after the surface.
- `port/graphics3d/vkvg/vkvg.def`: exports the four existing Vkh image entry points required by the Windows draw2d_vkvg DLL link; no vkvg/Vkh source changes.

### Generic GPU layer lifecycle

- `source/app/bred/gpu/compositor.h` and `compositor.cpp`: provide the default `renders_layer_externally()` query.
- `source/app/bred/gpu/layer.h` and `layer.cpp`: retain the external-rendering decision for the complete layer lifecycle.
- `source/app/bred/gpu/renderer.cpp`: bypass ordinary begin/clear/render-pass/end/submit operations for externally rendered layers while preserving layer bookkeeping and hooks.
- `source/app/bred/gpu/context.cpp`: finalize the layer texture before the compositor hook and avoid inserting a fence into an unrecorded external layer command buffer.
- `source/app/bred/gpu/tests/external_layer_rendering_contract_test.cpp`: source-level RED/GREEN coverage of the lifecycle branch and ordering.

### draw2d_vkvg target integration

- `source/app-graphics3d/draw2d_vkvg/graphics.h`: declares direct-target cache entries, active target state, external-rendering query, and cache helpers.
- `source/app-graphics3d/draw2d_vkvg/graphics.cpp`: selects composed textures, validates and wraps them, performs cache reuse transitions, flushes vkvg, synchronizes ca2 state, emits tracing, and destroys cache entries safely.
- `source/app-graphics3d/draw2d_vkvg/tests/direct_composed_layer_target_contract_test.cpp`: source-level RED/GREEN coverage of target identity, cache, transition, flush ordering, and ownership cleanup.

---

### Superseded wrapper task — do not execute

This original Task 1 is retained only as decision history. The user selected the existing `vkvg_surface_create_for_VkhImage()` API with a ca2-fabricated, ca2-owned `VkhImage`; therefore none of the following wrapper changes are executed. Task 1 is recorded complete with no source changes, and execution resumes at Task 2.

#### Original proposal: Add a safe raw-VkImage surface API to the VKVG wrapper

**Files:**
- Create: `port/graphics3d/vkvg/patches/0007-create-surface-for-vk-image.patch`
- Modify: `port/graphics3d/vkvg/include/vkvg.h:726-753`
- Modify: `port/graphics3d/vkvg/patches/vkvg_patch_manifest.cmake`
- Modify: `port/graphics3d/vkvg/vkvg.vcxproj:157-220`
- Modify: `port/graphics3d/vkvg/tests/vkvg_patch_materialization_contract.cmake`
- Do not modify: `port/graphics3d/vkvg/vkvg/**`

**Interfaces:**
- Consumes: `vkh_image_import(VkhDevice, VkImage, VkFormat, uint32_t, uint32_t) -> VkhImage`
- Consumes: `vkh_image_create_view(VkhImage, VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_ASPECT_COLOR_BIT)`
- Consumes: `vkvg_surface_create_for_VkhImage(VkvgDevice, void *) -> VkvgSurface`
- Produces: `vkvg_surface_create_for_vk_image(VkvgDevice, VkImage, VkFormat, uint32_t, uint32_t) -> VkvgSurface`
- Ownership: the returned surface owns one Vkh wrapper reference, view, and sampler; it never destroys the imported raw `VkImage` or its memory.

- [ ] **Step 1: Extend the materialization contract so it fails without the new helper**

Add `src/vkvg_surface.c` to the contract's `relative_sources`, read the staged surface source plus the wrapper public header, and add these exact checks:

```cmake
file(READ "${staged_output_dir}/src/vkvg_surface.c" surface_source)
file(READ "${WRAPPER_DIR}/include/vkvg.h" public_header)

foreach(required_text
  "vkvg_surface_create_for_vk_image"
  "vkh_image_import((VkhDevice)&dev->vkDev"
  "vkh_image_create_view(img, VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_ASPECT_COLOR_BIT)"
  "vkh_image_reference(img);"
  "vkh_image_destroy(img);")
  string(FIND "${surface_source}" "${required_text}" position)
  if(position EQUAL -1)
    message(FATAL_ERROR "Missing staged raw-VkImage surface behavior: ${required_text}")
  endif()
endforeach()

string(FIND "${surface_source}"
  "if (!surf->img->imported)" obsolete_imported_skip)
if(NOT obsolete_imported_skip EQUAL -1)
  message(FATAL_ERROR "Surface destruction still leaks imported wrapper resources")
endif()

string(FIND "${public_header}"
  "vkvg_surface_create_for_vk_image" public_declaration)
if(public_declaration EQUAL -1)
  message(FATAL_ERROR "Wrapper public header is missing raw-VkImage surface API")
endif()
```

Also require `0007-create-surface-for-vk-image.patch`, the staged `vkvg_surface.c` output, and the replacement `ClCompile` entry in the existing `vcxproj` checks.

- [ ] **Step 2: Run the wrapper contract to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$vkvgContractOutput = Join-Path $env:TEMP 'vkvg-direct-image-contract-red'
cmake `
  -DWRAPPER_DIR="$PWD\port\graphics3d\vkvg" `
  -DTEST_OUTPUT_DIR="$vkvgContractOutput" `
  -P port\graphics3d\vkvg\tests\vkvg_patch_materialization_contract.cmake
```

Expected: CMake exits nonzero because the manifest/header/staged surface implementation do not yet contain `vkvg_surface_create_for_vk_image`.

- [ ] **Step 3: Declare the wrapper-visible API**

Add this declaration immediately after `vkvg_surface_create_for_VkhImage()` in `port/graphics3d/vkvg/include/vkvg.h`:

```c
/**
 * @brief Create a vkvg surface that draws into an existing Vulkan image.
 *
 * The surface owns its Vkh wrapper, image view, and sampler. The supplied
 * VkImage and its device memory remain owned by the caller.
 */
vkvg_public VkvgSurface vkvg_surface_create_for_vk_image(
    VkvgDevice dev,
    VkImage image,
    VkFormat format,
    uint32_t width,
    uint32_t height);
```

- [ ] **Step 4: Create the numbered vkvg patch**

Create `0007-create-surface-for-vk-image.patch` against pristine `vkvg/src/vkvg_surface.c`. Its implementation must make three exact behavioral changes:

```c
VkvgSurface vkvg_surface_create_for_VkhImage(VkvgDevice dev, void *vkhImg) {
    /* existing validation and setup */
    VkhImage img = (VkhImage)vkhImg;
    vkh_image_reference(img);
    surf->img = img;
    /* existing sampler, secondary image, framebuffer, and transition setup */
}

vkvg_public VkvgSurface vkvg_surface_create_for_vk_image(
    VkvgDevice dev, VkImage image, VkFormat format, uint32_t width, uint32_t height) {
    if (image == VK_NULL_HANDLE || format != FB_COLOR_FORMAT || width == 0 || height == 0) {
        VkvgSurface surf = _create_surface(dev, FB_COLOR_FORMAT);
        surf->status = VKVG_STATUS_INVALID_IMAGE;
        return surf;
    }

    VkhImage img = vkh_image_import((VkhDevice)&dev->vkDev, image, format, width, height);
    if (img == NULL) {
        VkvgSurface surf = _create_surface(dev, FB_COLOR_FORMAT);
        surf->status = VKVG_STATUS_NO_MEMORY;
        return surf;
    }

    vkh_image_create_view(img, VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_ASPECT_COLOR_BIT);
    VkvgSurface surf = vkvg_surface_create_for_VkhImage(dev, img);
    vkh_image_destroy(img);
    return surf;
}
```

Replace the imported-image skip in `vkvg_surface_destroy()` with one unconditional wrapper release:

```c
    vkh_image_destroy(surf->img);
```

The new reference in `vkvg_surface_create_for_VkhImage()` preserves its caller-owned contract: an external caller retains its original reference, while the surface releases only the reference it acquired. The new raw-image helper releases its local reference after surface creation, leaving exactly the surface-owned reference. `vkh_image_destroy()` already destroys view/sampler bookkeeping but skips `vkDestroyImage()` and `vkFreeMemory()` when `img->imported` is true.

- [ ] **Step 5: Add the staged surface source to both build systems**

In `vkvg_patch_manifest.cmake`, append:

```cmake
  src/vkvg_surface.c
```

and append the new patch name:

```cmake
  0007-create-surface-for-vk-image.patch
```

In `vkvg.vcxproj`:

1. Add the new patch and pristine `vkvg\src\vkvg_surface.c` to `@(VkvgPatchInput)`.
2. Add `$(IntDir)vkvg-patched\src\vkvg_surface.c` to `MaterializeVkvgPatchedSources` outputs.
3. Replace the pristine surface compile item with:

```xml
<ClCompile Include="$(IntDir)vkvg-patched\src\vkvg_surface.c">
  <Link>vkvg\src\vkvg_surface.c</Link>
  <ObjectFileName>$(IntDir)vkvg_surface.obj</ObjectFileName>
  <AdditionalIncludeDirectories>$(ProjectDir)vkvg\src;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
</ClCompile>
```

- [ ] **Step 6: Preserve required line endings**

Run:

```powershell
unix2dos port\graphics3d\vkvg\include\vkvg.h
```

Do not run `unix2dos` on the `.patch` or `.cmake` files.

- [ ] **Step 7: Run the materialization contract to verify GREEN**

Run:

```powershell
$vkvgContractOutput = Join-Path $env:TEMP 'vkvg-direct-image-contract-green'
cmake `
  -DWRAPPER_DIR="$PWD\port\graphics3d\vkvg" `
  -DTEST_OUTPUT_DIR="$vkvgContractOutput" `
  -P port\graphics3d\vkvg\tests\vkvg_patch_materialization_contract.cmake
git -C port\graphics3d\vkvg\vkvg status --short
```

Expected: CMake exits `0`; the final Git command prints nothing.

- [ ] **Step 8: Build the vkvg wrapper**

Run:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows\port.sln `
  /t:vkvg /p:Configuration=Debug /p:Platform=x64 `
  /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: exit code `0`, with staged `vkvg_surface.c` compiled and `time-windows\x64\Debug\vkvg.dll` produced.

- [ ] **Step 9: Review the Task 1 diff**

Run:

```powershell
git -C port\graphics3d\vkvg diff --check -- `
  include/vkvg.h `
  patches/0007-create-surface-for-vk-image.patch `
  patches/vkvg_patch_manifest.cmake `
  tests/vkvg_patch_materialization_contract.cmake `
  vkvg.vcxproj
git -C port\graphics3d\vkvg diff -- `
  include/vkvg.h `
  patches/0007-create-surface-for-vk-image.patch `
  patches/vkvg_patch_manifest.cmake `
  tests/vkvg_patch_materialization_contract.cmake `
  vkvg.vcxproj
```

Expected: no whitespace errors; no diff exists below `port/graphics3d/vkvg/vkvg`.

- [ ] **Step 10: Commit only if explicitly authorized**

If the user has explicitly authorized commits, commit only the Task 1 files with message `feat: wrap external Vulkan images in vkvg`. Otherwise, leave the reviewed files unstaged and continue.

---

### Task 2: Add the generic external-layer rendering lifecycle

**Files:**
- Create: `source/app/bred/gpu/tests/external_layer_rendering_contract_test.cpp`
- Modify: `source/app/bred/gpu/compositor.h:42-60`
- Modify: `source/app/bred/gpu/compositor.cpp:98-120`
- Modify: `source/app/bred/gpu/layer.h:17-29`
- Modify: `source/app/bred/gpu/layer.cpp:118-142`
- Modify: `source/app/bred/gpu/renderer.cpp:1331-1391`
- Modify: `source/app/bred/gpu/renderer.cpp:1715-1757`
- Modify: `source/app/bred/gpu/context.cpp:4247-4304`

**Interfaces:**
- Produces: `virtual bool ::gpu::compositor::renders_layer_externally(::gpu::layer *)`, default `false`.
- Produces: `bool ::gpu::layer::m_bExternalRendering`, initialized `false` for each reused layer.
- Consumes later: `draw2d_vkvg::graphics::renders_layer_externally()` override from Task 3.
- Guarantees: external layers run compositor hooks and layer state bookkeeping without creating or submitting a ca2 layer command buffer.

- [ ] **Step 1: Write the failing external-layer lifecycle contract**

Create `external_layer_rendering_contract_test.cpp` with this complete source contract:

```cpp
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read(const std::filesystem::path & path)
   {

      std::ifstream stream(path, std::ios::binary);
      assert(stream);
      return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string & source,
      const std::string & beginMarker,
      const std::string & endMarker)
   {

      const auto begin = source.find(beginMarker);
      const auto end = source.find(endMarker, begin);
      assert(begin != std::string::npos);
      assert(end != std::string::npos);
      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto gpu = std::filesystem::path(__FILE__).parent_path().parent_path();
   const auto compositorHeader = read(gpu / "compositor.h");
   const auto compositorSource = read(gpu / "compositor.cpp");
   const auto layerHeader = read(gpu / "layer.h");
   const auto layerSource = read(gpu / "layer.cpp");
   const auto rendererSource = read(gpu / "renderer.cpp");
   const auto contextSource = read(gpu / "context.cpp");

   assert(compositorHeader.find(
      "virtual bool renders_layer_externally(::gpu::layer * pgpulayer);") !=
      std::string::npos);
   assert(compositorSource.find(
      "bool compositor::renders_layer_externally(::gpu::layer * pgpulayer)") !=
      std::string::npos);
   assert(layerHeader.find("bool m_bExternalRendering = false;") !=
      std::string::npos);

   const auto initializeLayer = section(
      layerSource,
      "void layer::initialize_gpu_layer(",
      "void layer::layer_start()");
   assert(initializeLayer.find("m_bExternalRendering = false;") !=
      std::string::npos);

   const auto startLayer = section(
      rendererSource,
      "void renderer::on_start_layer(layer* pgpulayer)",
      "void renderer::on_end_layer(layer* player)");
   const auto query = startLayer.find("renders_layer_externally(pgpulayer)");
   const auto externalState = startLayer.find("pgpulayer->start_layer_render();", query);
   const auto ordinaryBegin = startLayer.find("on_begin_render(pgpulayer);", externalState);
   const auto contextHook = startLayer.find("m_pgpucontext->on_start_layer(pgpulayer);", ordinaryBegin);
   const auto backendBegin = startLayer.find("_on_begin_render(pgpulayer);", contextHook);
   assert(query != std::string::npos);
   assert(externalState != std::string::npos);
   assert(ordinaryBegin != std::string::npos);
   assert(contextHook != std::string::npos);
   assert(backendBegin != std::string::npos);
   assert(query < externalState && externalState < ordinaryBegin);
   assert(ordinaryBegin < contextHook && contextHook < backendBegin);
   assert(startLayer.find("if (!pgpulayer->m_bExternalRendering)", query) !=
      std::string::npos);

   const auto endRender = section(
      rendererSource,
      "void renderer::on_end_render(::gpu::layer * pgpulayer)",
      "void renderer::_on_begin_render");
   const auto layerEnd = endRender.find("pgpulayer->layer_end();");
   const auto externalGuard = endRender.find(
      "if (!pgpulayer->m_bExternalRendering)", layerEnd);
   const auto backendEnd = endRender.find("_on_end_render(pgpulayer);", externalGuard);
   const auto submit = endRender.find("layer_end_submit();", backendEnd);
   const auto stateEnd = endRender.find("pgpulayer->end_layer_render();", submit);
   assert(layerEnd < externalGuard);
   assert(externalGuard < backendEnd && backendEnd < submit && submit < stateEnd);

   const auto contextStart = section(
      contextSource,
      "void context::on_start_layer(::gpu::layer * pgpulayer)",
      "void context::on_end_layer(::gpu::layer * pgpulayer)");
   assert(contextStart.find("auto ptexturesite = pgpulayer->texture(true);") <
      contextStart.find("on_start_layer_before_begin_render(pgpulayer);"));

   const auto contextEnd = section(
      contextSource,
      "void context::on_end_layer(::gpu::layer * pgpulayer)",
      "void context::on_create_texture");
   assert(contextEnd.find("if (!pgpulayer->m_bExternalRendering)") <
      contextEnd.find("insert_gpu_fence(true)"));

   return 0;

}
```

- [ ] **Step 2: Compile and run the lifecycle contract to verify RED**

Run:

```powershell
$externalLayerTest = Join-Path $env:TEMP 'external_layer_rendering_contract_test.exe'
g++ -std=c++17 `
  source\app\bred\gpu\tests\external_layer_rendering_contract_test.cpp `
  -o $externalLayerTest
& $externalLayerTest
```

Expected: the executable aborts because the query, layer flag, and guarded lifecycle do not exist.

- [ ] **Step 3: Add the default compositor query and layer state**

Add to `compositor.h` and `compositor.cpp`:

```cpp
virtual bool renders_layer_externally(::gpu::layer * pgpulayer);
```

```cpp
bool compositor::renders_layer_externally(::gpu::layer * pgpulayer)
{

   return false;

}
```

Add to `layer.h`:

```cpp
bool m_bExternalRendering = false;
```

Reset it beside `m_bIncludeInFrameComposition = true;` in `initialize_gpu_layer()`:

```cpp
m_bExternalRendering = false;
```

- [ ] **Step 4: Branch renderer start without opening a ca2 render pass**

At the beginning of `renderer::on_start_layer()`, replace the unconditional begin with:

```cpp
      auto pcompositor = m_pgpucontext->m_pgpucompositor;

      pgpulayer->m_bExternalRendering =
         pcompositor && pcompositor->renders_layer_externally(pgpulayer);

      if (pgpulayer->m_bExternalRendering)
      {

         pgpulayer->start_layer_render();

      }
      else
      {

         on_begin_render(pgpulayer);

      }
```

Keep `m_pgpucontext->on_start_layer(pgpulayer);` unconditional. Guard the later backend begin call:

```cpp
      if (!pgpulayer->m_bExternalRendering)
      {

         _on_begin_render(pgpulayer);

      }
```

Keep `gpu_layer_on_after_begin_render()` and `on_final_begin_render()` outside that guard.

- [ ] **Step 5: Branch renderer end without ending or submitting a nonexistent command buffer**

Keep `gpu_layer_on_before_end_render()` and `pgpulayer->layer_end()` unconditional. Wrap the existing window/offscreen `_on_end_render()` selection and `layer_end_submit()` together:

```cpp
      if (!pgpulayer->m_bExternalRendering)
      {

         auto bUseSwapChain = m_papplication->m_gpu.m_bUseSwapChainWindow;
         auto etypeGpuContext = m_pgpucontext->m_etype;

         if (!bUseSwapChain || etypeGpuContext != ::gpu::context::e_type_window)
         {

            _on_end_render(pgpulayer);

         }

         layer_end_submit();

      }

      pgpulayer->end_layer_render();
```

Do not move `pgpulayer->layer_end()` into the guard: it invokes the compositor end hook needed by externally rendered layers.

- [ ] **Step 6: Finalize the texture before the start hook and guard the fence insertion**

In `context::on_start_layer()`, retain `set_current_layer()` first, then move the complete `pgpulayer->texture(true)` placement/raw-size/size block before the compositor hook:

```cpp
      ::gpu::set_current_layer(pgpulayer);

      auto ptexturesite = pgpulayer->texture(true);
      ptexturesite->m_pointInput = m_pointInput;
      ptexturesite->m_pointOutput = m_pointOutput;

      if (ptexturesite->m_pgputextureSite->m_textureattributes.m_sizeRaw.is_empty())
      {

         ptexturesite->m_pgputextureSite->m_textureattributes.m_sizeRaw =
            ptexturesite->m_pgputextureSite->m_textureattributes.m_size;

      }

      ptexturesite->m_pgputextureSite->m_textureattributes.m_size = m_size;

      if (m_pgpucompositor)
      {

         m_pgpucompositor->on_start_layer_before_begin_render(pgpulayer);

      }
```

In `context::on_end_layer()`, retain the compositor end hook and guard only command-buffer fence insertion:

```cpp
      if (!pgpulayer->m_bExternalRendering)
      {

         ::cast<command_buffer> pcommandbuffer = ::gpu::current_command_buffer();
         pgpulayer->m_pgpufence = pcommandbuffer->insert_gpu_fence(true);

      }
```

- [ ] **Step 7: Convert modified C++ files to CRLF**

Run:

```powershell
unix2dos source\app\bred\gpu\compositor.h
unix2dos source\app\bred\gpu\compositor.cpp
unix2dos source\app\bred\gpu\layer.h
unix2dos source\app\bred\gpu\layer.cpp
unix2dos source\app\bred\gpu\renderer.cpp
unix2dos source\app\bred\gpu\context.cpp
unix2dos source\app\bred\gpu\tests\external_layer_rendering_contract_test.cpp
```

- [ ] **Step 8: Run the lifecycle contract to verify GREEN**

Run:

```powershell
$externalLayerTest = Join-Path $env:TEMP 'external_layer_rendering_contract_test.exe'
g++ -std=c++17 `
  source\app\bred\gpu\tests\external_layer_rendering_contract_test.cpp `
  -o $externalLayerTest
& $externalLayerTest
```

Expected: exit code `0`.

- [ ] **Step 9: Run existing layer contracts and build core GPU modules**

Run:

```powershell
$offscreenLayerTest = Join-Path $env:TEMP 'offscreen_layer_end_contract_test.exe'
g++ -std=c++17 source\app\bred\gpu\tests\offscreen_layer_end_contract_test.cpp -o $offscreenLayerTest
& $offscreenLayerTest

$compositionLayerTest = Join-Path $env:TEMP 'gpu_memory_image_layer_composition_contract_test.exe'
g++ -std=c++17 source\app\bred\gpu\tests\gpu_memory_image_layer_composition_contract_test.cpp -o $compositionLayerTest
Push-Location source\app
try { & $compositionLayerTest } finally { Pop-Location }

& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows\SceneFoundry.sln `
  /t:bred /p:Configuration=Debug /p:Platform=x64 `
  /p:BuildProjectReferences=false /m:1 /v:minimal
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows\SceneFoundry.sln `
  /t:gpu_vulkan /p:Configuration=Debug /p:Platform=x64 `
  /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: all contracts and both builds exit `0`. Because the default compositor query returns false, existing renderers retain their prior lifecycle.

- [ ] **Step 10: Review the Task 2 diff**

Run:

```powershell
git -C source\app diff --check -- bred/gpu
git -C source\app diff -- `
  bred/gpu/compositor.h bred/gpu/compositor.cpp `
  bred/gpu/layer.h bred/gpu/layer.cpp `
  bred/gpu/renderer.cpp bred/gpu/context.cpp `
  bred/gpu/tests/external_layer_rendering_contract_test.cpp
```

Expected: no whitespace errors; the new branch defaults to existing behavior and does not mention vkvg or Vulkan types.

- [ ] **Step 11: Commit only if explicitly authorized**

If commits are authorized, commit only Task 2 files with message `feat: support externally rendered GPU layers`. Otherwise, leave them unstaged.

---

### Task 3: Render composed draw2d_vkvg layers into cached ca2 textures

**Files:**
- Create: `source/app-graphics3d/draw2d_vkvg/tests/direct_composed_layer_target_contract_test.cpp`
- Modify: `port/graphics3d/vkvg/vkvg.def`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.h:29-110`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.cpp:139-190`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.cpp:6296-6346`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.cpp:8747-8862`
- Modify: `source/app-graphics3d/draw2d_vkvg/graphics.cpp:8961-8987`

**Interfaces:**
- Consumes: `vkh_image_import(VkhDevice, VkImage, VkFormat, uint32_t, uint32_t) -> VkhImage`.
- Consumes: `vkh_image_create_view(VkhImage, VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_ASPECT_COLOR_BIT)`.
- Consumes: existing `vkvg_surface_create_for_VkhImage(VkvgDevice, void *) -> VkvgSurface`.
- Consumes: `::gpu::compositor::renders_layer_externally()` from Task 2.
- Consumes: `::gpu_vulkan::texture::set_state(command_buffer, e_texture_state_color_attachment)`.
- Consumes: `::gpu_vulkan::texture::from_external_state(e_texture_state_color_attachment, e_texture_state_color_attachment)`.
- Produces: `draw2d_vkvg::graphics::prepare_vkvg_render_target(::gpu::texture *)`.
- Produces: one cached surface/context per `{texture pointer, VkImage, VkFormat, width, height}` identity.
- Produces: the same `VkImage` at vkvg draw time and later layer composition time.

- [ ] **Step 1: Write the failing direct-target contract**

Create `direct_composed_layer_target_contract_test.cpp`:

```cpp
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read(const std::filesystem::path & path)
   {

      std::ifstream stream(path, std::ios::binary);
      assert(stream);
      return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string & source,
      const std::string & beginMarker,
      const std::string & endMarker)
   {

      const auto begin = source.find(beginMarker);
      const auto end = source.find(endMarker, begin);
      assert(begin != std::string::npos);
      assert(end != std::string::npos);
      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto draw2dVkvg = std::filesystem::path(__FILE__).parent_path().parent_path();
   const auto header = read(draw2dVkvg / "graphics.h");
   const auto source = read(draw2dVkvg / "graphics.cpp");

   assert(header.find(
      "bool renders_layer_externally(::gpu::layer * pgpulayer) override;") !=
      std::string::npos);
   assert(header.find("class direct_target") != std::string::npos);
   assert(header.find("m_pdirecttargetActive") != std::string::npos);
   assert(header.find("prepare_vkvg_render_target(::gpu::texture * pgputexture)") !=
      std::string::npos);

   const auto targetSelection = section(
      source,
      "::gpu::texture_site* graphics::current_target_texture(",
      "bool graphics::is_gpu_oriented()");
   const auto composed = targetSelection.find(
      "pgpulayer->m_bIncludeInFrameComposition");
   const auto rendererTarget = targetSelection.find(
      "current_render_target_texture(pgpulayer)", composed);
   const auto privateSurface = targetSelection.find(
      "vkvg_surface_get_vk_image(m_vkvgsurface)", rendererTarget);
   assert(composed < rendererTarget && rendererTarget < privateSurface);

   const auto prepare = section(
      source,
      "void graphics::prepare_vkvg_render_target(",
      "void graphics::maintain_vkvg_direct_target_cache()");
   for (const auto * required : {
      "::gpu_vulkan::texture",
      "VK_FORMAT_B8G8R8A8_UNORM",
      "VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT",
      "VK_IMAGE_USAGE_SAMPLED_BIT",
      "vkh_image_import",
      "vkh_image_create_view",
      "vkvg_surface_create_for_VkhImage",
      "beginSingleTimeCommands",
      "e_texture_state_color_attachment",
      "endSingleTimeCommands",
      "from_external_state",
      "m_pdirecttargetActive"})
   {

      assert(prepare.find(required) != std::string::npos);

   }

   const auto startHook = section(
      source,
      "void graphics::on_start_layer_before_begin_render(",
      "} // namespace draw2d_vkvg");
   assert(startHook.find("prepare_vkvg_render_target") <
      startHook.find("vkvg_clear(vkvgcontext)"));

   const auto endLayer = section(
      source,
      "void graphics::end_layer(bool bClosingLayer)",
      "void graphics::on_present()");
   const auto flush = endLayer.find("vkvg_flush(vkvgcontext);");
   const auto state = endLayer.find("from_external_state(", flush);
   const auto genericEnd = endLayer.find(
      "::gpu::graphics::end_layer(bClosingLayer);", state);
   const auto unlock = endLayer.find("m_queuehostcalllock.unlock();", genericEnd);
   assert(flush < state && state < genericEnd && genericEnd < unlock);

   const auto destroyTarget = section(
      source,
      "void graphics::destroy_vkvg_direct_target(",
      "void graphics::clear_vkvg_direct_target_cache()");
   assert(destroyTarget.find("vkvg_destroy") <
      destroyTarget.find("vkvg_surface_destroy"));
   assert(destroyTarget.find("vkvg_surface_destroy") <
      destroyTarget.find("vkh_image_destroy"));
   assert(destroyTarget.find("vkh_image_destroy") <
      destroyTarget.find("m_ptexture.release()"));

   assert(source.find(
      "return pgpulayer && pgpulayer->m_bIncludeInFrameComposition;") !=
      std::string::npos);
   assert(source.find("set_target_image(", source.find(
      "void graphics::prepare_vkvg_render_target(")) == std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Compile and run the target contract to verify RED**

Run:

```powershell
$vkvgTargetTest = Join-Path $env:TEMP 'direct_composed_layer_target_contract_test.exe'
g++ -std=c++17 `
  source\app-graphics3d\draw2d_vkvg\tests\direct_composed_layer_target_contract_test.cpp `
  -o $vkvgTargetTest
& $vkvgTargetTest
```

Expected: the executable aborts because the cache, target selection, Vkh import, existing vkvg surface call, external query, and state handoff are absent.

- [ ] **Step 3: Declare direct-target cache state and helpers**

Before `graphics` in `graphics.h`, add:

```cpp
   class direct_target :
      virtual public ::particle
   {
   public:

      ::pointer<::gpu_vulkan::texture> m_ptexture;
      VkImage m_vkimage = VK_NULL_HANDLE;
      VkFormat m_vkformat = VK_FORMAT_UNDEFINED;
      ::i32_size m_size;
      VkhImage m_vkhimage = nullptr;
      VkvgSurface m_vkvgsurface = nullptr;
      VkvgContext m_vkvgcontext = nullptr;
      ::u64 m_uFrameSerial = 0;

   };
```

Add these members and declarations to `graphics`:

```cpp
      ::pointer_array<direct_target> m_directtargeta;
      ::pointer<direct_target> m_pdirecttargetActive;
      ::u64 m_uDirectTargetFrameSerial = 0;

      bool renders_layer_externally(::gpu::layer * pgpulayer) override;
      void prepare_vkvg_render_target(::gpu::texture * pgputexture);
      void maintain_vkvg_direct_target_cache();
      void destroy_vkvg_direct_target(direct_target * pdirecttarget);
      void clear_vkvg_direct_target_cache();
```

Keep `m_vkvgsurface`, `m_vkvgcontext`, and `m_ptexturesiteCurrent` unchanged for the non-composed private path.

- [ ] **Step 4: Select the ca2 texture for composed layers**

Insert this branch at the start of `current_target_texture()` before the existing private-surface wrapper logic:

```cpp
      if (pgpulayer && pgpulayer->m_bIncludeInFrameComposition)
      {

         auto pgpucontext = gpu_context();

         if (!pgpucontext)
         {

            throw ::exception(
               error_wrong_state,
               "VKVG has no GPU context for the active composition layer.");

         }

         return pgpucontext->get_gpu_renderer()->current_render_target_texture(pgpulayer);

      }
```

Add the external ownership query:

```cpp
bool graphics::renders_layer_externally(::gpu::layer * pgpulayer)
{

   return pgpulayer && pgpulayer->m_bIncludeInFrameComposition;

}
```

- [ ] **Step 5: Implement target validation and exact-identity cache lookup**

`prepare_vkvg_render_target()` begins with these checks:

```cpp
      if (!pgputexture)
      {

         throw ::exception(error_wrong_state, "VKVG has no composed layer texture.");

      }

      ::cast<::gpu_vulkan::texture> ptexture = pgputexture;

      if (!ptexture || ptexture->m_vkimage == VK_NULL_HANDLE)
      {

         throw ::exception(error_wrong_state, "VKVG requires a valid Vulkan layer texture.");

      }

      if (ptexture->m_vkformat != VK_FORMAT_B8G8R8A8_UNORM)
      {

         throw ::exception(error_not_supported, "VKVG direct layers require BGRA8 UNORM.");

      }

      const auto usage = ptexture->m_vkimageusageflags;
      const auto requiredUsage =
         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;

      auto pgpucontext = gpu_context();

      if ((usage & requiredUsage) != requiredUsage ||
          ptexture->mip_count() != 1 || ptexture->layer_count() != 1 ||
          ptexture->size().is_empty() ||
          ptexture->size() != pgpucontext->size())
      {

         throw ::exception(error_wrong_state, "VKVG composed layer texture is incompatible.");

      }
```

Search `m_directtargeta` by texture pointer. An entry is a hit only when texture pointer, `VkImage`, format, and size all match. If the texture pointer matches but any identity field differs, call `destroy_vkvg_direct_target()`, erase that entry, and continue as a miss.

Before either first use or reuse, wait a current target-reuse fence when one exists:

```cpp
      auto psynchronization = ptexture->synchronization();
      auto pfence = psynchronization ? psynchronization->in_flight_fence() : nullptr;

      if (pfence)
      {

         pfence->wait_gpu_fence();

      }
```

- [ ] **Step 6: Implement cache-hit transition and cache-miss surface creation**

First, expose only the existing Vkh entry points required by ca2 through `port/graphics3d/vkvg/vkvg.def`:

```def
LIBRARY "vkvg"

EXPORTS
vkh_image_import
vkh_image_status
vkh_image_create_view
vkh_image_destroy
```

This is a Windows DLL-link boundary change only. Do not add `VKH_SHARED_BUILD`, export the rest of Vkh, or patch vkvg/Vkh source.

For an exact cache hit, transition the ca2-tracked image back to vkvg's expected color state on the shared graphics queue:

```cpp
      auto pgpucommandbuffer = pgpucontext->beginSingleTimeCommands(
         pgpucontext->m_pgpudevice->graphics_queue());
      ptexture->set_state(
         pgpucommandbuffer,
         ::gpu::e_texture_state_color_attachment);
      pgpucontext->endSingleTimeCommands(pgpucommandbuffer);

      pdirecttarget->m_uFrameSerial = ++m_uDirectTargetFrameSerial;
      m_pdirecttargetActive = pdirecttarget;
```

For a miss, fabricate the ca2-owned `VkhImage`, then create local vkvg handles and publish the cache entry only after all three succeed. The address of `gpu_vulkan::device::m_vkdevice` is stable for the cache lifetime and mirrors vkvg's internal Vkh-device view convention:

```cpp
      ::cast<::gpu_vulkan::context> pcontextVulkan = pgpucontext;

      if (!pcontextVulkan)
      {

         throw ::exception(error_wrong_state, "VKVG requires a Vulkan GPU context.");

      }

      auto pgpudeviceVulkan = pcontextVulkan->m_pgpudevice;
      auto vkhdevice = reinterpret_cast<VkhDevice>(&pgpudeviceVulkan->m_vkdevice);

      auto vkhimage = vkh_image_import(
         vkhdevice,
         ptexture->m_vkimage,
         ptexture->m_vkformat,
         (::u32)ptexture->width(),
         (::u32)ptexture->height());

      if (!vkhimage || vkh_image_status(vkhimage) != VK_SUCCESS)
      {

         throw ::exception(error_failed, "VKVG could not import the composed layer image.");

      }

      vkh_image_create_view(
         vkhimage,
         VK_IMAGE_VIEW_TYPE_2D,
         VK_IMAGE_ASPECT_COLOR_BIT);

      auto vkvgsurface = vkvg_surface_create_for_VkhImage(
         get_vkvg_device(),
         vkhimage);

      if (!vkvgsurface || vkvg_surface_status(vkvgsurface) != VKVG_STATUS_SUCCESS)
      {

         vkh_image_destroy(vkhimage);
         throw ::exception(error_failed, "VKVG could not wrap the composed layer image.");

      }

      auto vkvgcontext = vkvg_create(vkvgsurface);

      if (!vkvgcontext || vkvg_status(vkvgcontext) != VKVG_STATUS_SUCCESS)
      {

         vkvg_surface_destroy(vkvgsurface);
         vkh_image_destroy(vkhimage);
         throw ::exception(error_failed, "VKVG could not create a context for the composed layer image.");

      }

      auto pdirecttargetNew = allocateø direct_target();
      pdirecttargetNew->m_ptexture = ptexture;
      pdirecttargetNew->m_vkimage = ptexture->m_vkimage;
      pdirecttargetNew->m_vkformat = ptexture->m_vkformat;
      pdirecttargetNew->m_size = ptexture->size();
      pdirecttargetNew->m_vkhimage = vkhimage;
      pdirecttargetNew->m_vkvgsurface = vkvgsurface;
      pdirecttargetNew->m_vkvgcontext = vkvgcontext;
      pdirecttargetNew->m_uFrameSerial = ++m_uDirectTargetFrameSerial;
      m_directtargeta.add(pdirecttargetNew);
      m_pdirecttargetActive = pdirecttargetNew;

      ptexture->from_external_state(
         ::gpu::e_texture_state_color_attachment,
         ::gpu::e_texture_state_color_attachment);
```

Emit one start trace after hit/miss selection:

```cpp
      auto pgpulayer = ::gpu::current_layer();

      informationf(
         "draw2d_vkvg direct start layer=%d composed=%d texture=%p image=0x%llx surface=%p context=%p cache=%s layout=%d access=0x%llx bypass=1",
         pgpulayer ? pgpulayer->m_iLayerIndex : -1,
         pgpulayer && pgpulayer->m_bIncludeInFrameComposition ? 1 : 0,
         ptexture.m_p,
         (::u64)ptexture->m_vkimage,
         m_pdirecttargetActive->m_vkvgsurface,
         m_pdirecttargetActive->m_vkvgcontext,
         bCacheHit ? "hit" : "miss",
         (::i32)ptexture->mip_layer_state(0, 0).m_vkimagelayout,
         (::u64)ptexture->mip_layer_state(0, 0).m_vkaccessflags);
```

Use a local `bool bCacheHit` set by the exact-identity lookup.

- [ ] **Step 7: Bound and destroy the cache safely**

Implement cleanup in this order:

```cpp
void graphics::destroy_vkvg_direct_target(direct_target * pdirecttarget)
{

   if (pdirecttarget->m_vkvgcontext)
   {

      vkvg_destroy(pdirecttarget->m_vkvgcontext);
      pdirecttarget->m_vkvgcontext = nullptr;

   }

   if (pdirecttarget->m_vkvgsurface)
   {

      vkvg_surface_destroy(pdirecttarget->m_vkvgsurface);
      pdirecttarget->m_vkvgsurface = nullptr;

   }

   if (pdirecttarget->m_vkhimage)
   {

      vkh_image_destroy(pdirecttarget->m_vkhimage);
      pdirecttarget->m_vkhimage = nullptr;

   }

   pdirecttarget->m_ptexture.release();

}
```

`clear_vkvg_direct_target_cache()` clears `m_pdirecttargetActive`, destroys every entry, then clears the array. Call it at the start of `graphics::~graphics()` before `DeleteDC()`.

`maintain_vkvg_direct_target_cache()` obtains the window attachment's frame count and counts persistent layers whose `m_bIncludeInFrameComposition` flag is true. It permits `frameCount * maximum(1, composedLayerCount) + 1` entries, then repeatedly removes the least-recently-used entry that is not `m_pdirecttargetActive`. This retains one surface/context for every rotating physical image of every composed layer. Call it after publishing/selecting the active entry. Do not evict the active entry.

- [ ] **Step 8: Route all composed drawing through the active context**

At the beginning of `vkvg_context()`, return the active direct target before the legacy external-state/private-context logic:

```cpp
      if (m_pdirecttargetActive)
      {

         return m_pdirecttargetActive->m_vkvgcontext;

      }
```

Update `on_start_layer_before_begin_render()`:

```cpp
void graphics::on_start_layer_before_begin_render(::gpu::layer * pgpulayer)
{

   if (pgpulayer && pgpulayer->m_bIncludeInFrameComposition)
   {

      auto pgputexturesite = current_target_texture(pgpulayer);

      if (!pgputexturesite || !pgputexturesite->gpu_texture())
      {

         throw ::exception(error_wrong_state, "VKVG composed layer has no target texture.");

      }

      prepare_vkvg_render_target(pgputexturesite->gpu_texture());

   }
   else
   {

      m_pdirecttargetActive.release();

   }

   auto vkvgcontext = vkvg_context();
   vkvg_clear(vkvgcontext);

}
```

- [ ] **Step 9: Flush and publish the final Vulkan state before generic layer end**

Immediately after `vkvg_flush(vkvgcontext);` in `end_layer()`, add:

```cpp
            if (m_pdirecttargetActive)
            {

               auto ptexture = m_pdirecttargetActive->m_ptexture;
               ptexture->from_external_state(
                  ::gpu::e_texture_state_color_attachment,
                  ::gpu::e_texture_state_color_attachment);

               auto pgpulayer = ::gpu::current_layer();

               informationf(
                  "draw2d_vkvg direct end layer=%d composed=%d texture=%p image=0x%llx surface=%p context=%p layout=%d access=0x%llx bypass=1",
                  pgpulayer ? pgpulayer->m_iLayerIndex : -1,
                  pgpulayer && pgpulayer->m_bIncludeInFrameComposition ? 1 : 0,
                  ptexture.m_p,
                  (::u64)ptexture->m_vkimage,
                  m_pdirecttargetActive->m_vkvgsurface,
                  m_pdirecttargetActive->m_vkvgcontext,
                  (::i32)ptexture->mip_layer_state(0, 0).m_vkimagelayout,
                  (::u64)ptexture->mip_layer_state(0, 0).m_vkaccessflags);

            }
```

Preserve this ordering:

```text
vkvg_flush
ca2 tracked-state synchronization
gpu::graphics::end_layer
queue host-call unlock
```

Do not call `set_target_image()` and do not add a layer copy.

- [ ] **Step 10: Convert modified draw2d_vkvg C++ files to CRLF**

Run:

```powershell
unix2dos source\app-graphics3d\draw2d_vkvg\graphics.h
unix2dos source\app-graphics3d\draw2d_vkvg\graphics.cpp
unix2dos source\app-graphics3d\draw2d_vkvg\tests\direct_composed_layer_target_contract_test.cpp
```

- [ ] **Step 11: Run direct-target and existing queue-handoff contracts**

Run:

```powershell
$vkvgTargetTest = Join-Path $env:TEMP 'direct_composed_layer_target_contract_test.exe'
g++ -std=c++17 `
  source\app-graphics3d\draw2d_vkvg\tests\direct_composed_layer_target_contract_test.cpp `
  -o $vkvgTargetTest
& $vkvgTargetTest

$vkvgQueueTest = Join-Path $env:TEMP 'queue_layer_handoff_contract_test.exe'
g++ -std=c++17 `
  source\app-graphics3d\draw2d_vkvg\tests\queue_layer_handoff_contract_test.cpp `
  -o $vkvgQueueTest
& $vkvgQueueTest
```

Expected: both exit `0`. If the existing queue test's diagnostic text still says “layer-copy handoff,” update only that message to “direct layer handoff”; keep its flush → generic end → unlock ordering assertion.

- [ ] **Step 12: Build draw2d_vkvg**

Run:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows\port.sln `
  /t:vkvg /p:Configuration=Debug /p:Platform=x64 `
  /p:BuildProjectReferences=false /m:1 /v:minimal

& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows\SceneFoundry.sln `
  /t:draw2d_vkvg /p:Configuration=Debug /p:Platform=x64 `
  /p:BuildProjectReferences=false /m:1 /v:minimal
```

Expected: exit code `0` and `time-windows\x64\Debug\draw2d_vkvg.dll` produced.

- [ ] **Step 13: Review the Task 3 diff**

Run:

```powershell
git -C source\app-graphics3d diff --check -- draw2d_vkvg
git -C source\app-graphics3d diff -- `
  draw2d_vkvg/graphics.h `
  draw2d_vkvg/graphics.cpp `
  draw2d_vkvg/tests/direct_composed_layer_target_contract_test.cpp `
  draw2d_vkvg/tests/queue_layer_handoff_contract_test.cpp
```

Expected: no whitespace errors; composed selection precedes the untouched private-surface branch; no call to `layer_end_copy()` or `set_target_image()` was added.

- [ ] **Step 14: Commit only if explicitly authorized**

If commits are authorized, commit only Task 3 files with message `feat: render vkvg into composed Vulkan layers`. Otherwise, leave them unstaged.

---

### Task 4: Verify the integrated continuum configuration

**Files:**
- Verify only: `T:/Dropbox/application/app-graphics3d/continuum/graphics3d_output.txt`
- Verify only: `T:/Dropbox/application/app-graphics3d/continuum/windows/draw2d.txt`
- Verify only: `T:/Dropbox/application/app-graphics3d/continuum/windows/graphics3d.txt`
- Build: `solution-windows/SceneFoundry.sln`
- Run: `time-windows/x64/Debug/shared_app_graphics3d_continuum.exe`

**Interfaces:**
- Consumes: Task 2 and Task 3 interfaces plus the existing Vkh/vkvg APIs used by the ca2-owned adapter.
- Verifies: the vkvg target `VkImage` is the same image bound by `merge_layers()` and Vulkan validation remains clean.
- Produces: runtime evidence and a scoped final diff; no new production interface.

- [ ] **Step 1: Run the complete focused contract set**

Run:

```powershell
$externalLayerTest = Join-Path $env:TEMP 'external_layer_rendering_contract_test.exe'
g++ -std=c++17 source\app\bred\gpu\tests\external_layer_rendering_contract_test.cpp -o $externalLayerTest
& $externalLayerTest

$vkvgTargetTest = Join-Path $env:TEMP 'direct_composed_layer_target_contract_test.exe'
g++ -std=c++17 source\app-graphics3d\draw2d_vkvg\tests\direct_composed_layer_target_contract_test.cpp -o $vkvgTargetTest
& $vkvgTargetTest

$vkvgQueueTest = Join-Path $env:TEMP 'queue_layer_handoff_contract_test.exe'
g++ -std=c++17 source\app-graphics3d\draw2d_vkvg\tests\queue_layer_handoff_contract_test.cpp -o $vkvgQueueTest
& $vkvgQueueTest

$vkvgContractOutput = Join-Path $env:TEMP 'vkvg-direct-image-contract-final'
cmake `
  -DWRAPPER_DIR="$PWD\port\graphics3d\vkvg" `
  -DTEST_OUTPUT_DIR="$vkvgContractOutput" `
  -P port\graphics3d\vkvg\tests\vkvg_patch_materialization_contract.cmake
```

Expected: every command exits `0`.

- [ ] **Step 2: Build the affected dependency chain and application**

Run each target separately so a failing project is unambiguous:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
$common = @(
  '/p:Configuration=Debug',
  '/p:Platform=x64',
  '/p:BuildProjectReferences=false',
  '/m:1',
  '/v:minimal')

& $msbuild solution-windows\port.sln /t:vkvg @common
& $msbuild solution-windows\SceneFoundry.sln /t:bred @common
& $msbuild solution-windows\SceneFoundry.sln /t:gpu_vulkan @common
& $msbuild solution-windows\SceneFoundry.sln /t:draw2d_vkvg @common
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum @common
```

Expected: all five targets exit `0`; the final executable timestamp updates.

- [ ] **Step 3: Confirm the requested runtime configuration without modifying it**

Run:

```powershell
Get-Content -LiteralPath 'T:\Dropbox\application\app-graphics3d\continuum\graphics3d_output.txt'
Get-Content -LiteralPath 'T:\Dropbox\application\app-graphics3d\continuum\windows\draw2d.txt'
Get-Content -LiteralPath 'T:\Dropbox\application\app-graphics3d\continuum\windows\graphics3d.txt'
```

Expected output:

```text
on_screen
vkvg
vulkan
```

If these values differ, stop runtime verification and report the exact current values. Do not rewrite the user's external configuration implicitly.

- [ ] **Step 4: Run continuum with Vulkan validation and collect the direct-target trace**

Launch:

```powershell
& 'time-windows\x64\Debug\shared_app_graphics3d_continuum.exe'
```

Keep the application open long enough to render several rotating frames, then close it normally. Collect the application log and find `draw2d_vkvg direct start`, `draw2d_vkvg direct end`, and the existing `merge_layers` input binding trace. For each composed 2D layer, record the raw hexadecimal `VkImage` from the start/end messages and compare it with the corresponding merge input.

Expected:

- Every cache miss is followed by hits as rotating images recur.
- Start and end for one layer use the same texture, `VkImage`, surface, and context.
- The `VkImage` supplied to `merge_layers()` equals the one in the vkvg direct trace.
- The UI appears over the 3D scene.
- Vulkan validation emits no render-pass, image-layout, queue-synchronization, pipeline-binding, or object-lifetime errors.
- No layer copy appears in the trace.

- [ ] **Step 5: Use RenderDoc only as optional identity confirmation**

If RenderDoc can capture the on-screen configuration, inspect the vkvg color attachment and the later merge descriptor and confirm their `VkImage` identity. Do not treat RenderDoc capture failure as a test failure; the trace comparison is authoritative for this offscreen/direct-layer architecture.

- [ ] **Step 6: Run final cleanliness and scope checks**

Run:

```powershell
git -C port\graphics3d\vkvg\vkvg status --short
git -C port\graphics3d\vkvg diff --check -- `
  include/vkvg.h patches tests/vkvg_patch_materialization_contract.cmake vkvg.vcxproj
git -C source\app diff --check -- `
  bred/gpu/compositor.h bred/gpu/compositor.cpp `
  bred/gpu/layer.h bred/gpu/layer.cpp `
  bred/gpu/renderer.cpp bred/gpu/context.cpp `
  bred/gpu/tests/external_layer_rendering_contract_test.cpp
git -C source\app-graphics3d diff --check -- draw2d_vkvg
```

Expected: the pristine vkvg submodule status is empty and all `diff --check` commands exit `0`.

- [ ] **Step 7: Report evidence without committing unless requested**

Report:

- focused contract exit codes;
- the five MSBuild target results;
- the composed-layer `VkImage` identity comparison;
- whether the UI appeared;
- Vulkan validation status;
- any remaining temporary tracing that should be reduced after the user confirms runtime behavior.

Do not stage or commit unless the user explicitly requests it.
