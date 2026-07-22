# GPU Memory-Image Layer Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent GPU-backed memory-image render layers from being automatically composited at window position `(0,0)` while preserving their GPU textures for explicit drawing at the intended destination.

**Architecture:** `gpu::layer` records explicit automatic-composition intent, reset to enabled whenever a reusable layer is initialized. Generic `gpu::graphics` opts out only layers that render into an associated `image::image`; the closing renderer derives one filtered composition list and uses it consistently for completion waits, layer merging, and merge-semaphore collection.

**Tech Stack:** C++20, SceneFoundry `bred` GPU framework, draw2d graphics leases and scoped layers, source-contract executables, Visual Studio/MSBuild Debug x64.

## Global Constraints

- Keep offscreen image layers alive and usable through the GPU-only texture-sampling path.
- Preserve automatic composition for main 2D GUI, 3D scene, swap-chain, and offscreen scene layers.
- Do not infer composition intent from `gpu::enum_output` or exclude every `e_output_gpu_buffer` layer.
- Do not remove excluded layers from the device-wide layer array.
- Reset composition intent whenever a reusable `gpu::layer` is initialized.
- Use the same filtered list for final-merge waits, `merge_layers`, and merge-semaphore collection.
- Preserve CRLF line endings in modified C++ source, header, and test files.
- Do not modify or stage unrelated worktree changes.

---

### Task 1: Capture automatic-composition intent on each GPU layer

**Files:**
- Create: `source/app/bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp`
- Modify: `source/app/bred/gpu/layer.h:20-23`
- Modify: `source/app/bred/gpu/layer.cpp:115-135`
- Modify: `source/app/bred/gpu/graphics.h:56-66`
- Modify: `source/app/bred/gpu/graphics.cpp:113-121`

**Interfaces:**
- Produces: `bool gpu::layer::m_bIncludeInFrameComposition`, default and reinitialization value `true`
- Produces: `void gpu::graphics::on_start_layer_before_begin_render(::gpu::layer *) override`
- Consumes: inherited `draw2d::graphics::m_pimage` as the semantic indication that the layer renders an image cache target

- [ ] **Step 1: Write the failing composition-intent contract**

Create `source/app/bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp` with:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char * pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

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
      assert(begin < end);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto layerHeader = read_file("bred/gpu/layer.h");
   const auto layerSource = read_file("bred/gpu/layer.cpp");
   const auto graphicsHeader = read_file("bred/gpu/graphics.h");
   const auto graphicsSource = read_file("bred/gpu/graphics.cpp");

   assert(layerHeader.find(
      "bool m_bIncludeInFrameComposition = true;") !=
      std::string::npos);

   const auto initializeLayer = section(
      layerSource,
      "void layer::initialize_gpu_layer(",
      "void layer::layer_start()");
   assert(initializeLayer.find(
      "m_bIncludeInFrameComposition = true;") !=
      std::string::npos);

   assert(graphicsHeader.find(
      "void on_start_layer_before_begin_render(::gpu::layer * pgpulayer) override;") !=
      std::string::npos);

   const auto imageLayerPolicy = section(
      graphicsSource,
      "void graphics::on_start_layer_before_begin_render(",
      "void graphics::on_begin_layer_scope()");
   assert(imageLayerPolicy.find(
      "::gpu::compositor::on_start_layer_before_begin_render(pgpulayer);") !=
      std::string::npos);
   assert(imageLayerPolicy.find("if (m_pimage)") != std::string::npos);
   assert(imageLayerPolicy.find(
      "pgpulayer->m_bIncludeInFrameComposition = false;") !=
      std::string::npos);
   assert(imageLayerPolicy.find("m_eoutput") == std::string::npos);
   assert(imageLayerPolicy.find("e_output_gpu_buffer") == std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Compile and run the new contract to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app`:

```powershell
g++ bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
```

Expected: the executable aborts because `m_bIncludeInFrameComposition` and the graphics policy hook do not exist.

- [ ] **Step 3: Add and reset the per-layer composition flag**

Add this member beside `m_bFirstLayer` and `m_bClosingLayer` in `source/app/bred/gpu/layer.h`:

```cpp
      bool m_bIncludeInFrameComposition = true;
```

In `layer::initialize_gpu_layer`, immediately after assigning `m_iLayerIndex`, reset the reusable layer:

```cpp
      m_bIncludeInFrameComposition = true;
```

Do not derive this value from the context output type.

- [ ] **Step 4: Declare the generic image-backed graphics policy hook**

Add this override beside the layer lifecycle declarations in `source/app/bred/gpu/graphics.h`:

```cpp
      void on_start_layer_before_begin_render(
         ::gpu::layer * pgpulayer) override;
```

- [ ] **Step 5: Implement the image-backed layer policy**

Insert this method in `source/app/bred/gpu/graphics.cpp` immediately before `graphics::on_begin_layer_scope`:

```cpp
   void graphics::on_start_layer_before_begin_render(
      ::gpu::layer * pgpulayer)
   {

      ::gpu::compositor::on_start_layer_before_begin_render(pgpulayer);

      if (m_pimage)
      {

         pgpulayer->m_bIncludeInFrameComposition = false;

      }

   }
```

The layer is already current when `gpu::context` calls this hook. The decision is captured on the layer before backend rendering begins and remains valid after the image graphics lease clears its `m_pimage` association.

- [ ] **Step 6: Preserve CRLF and run the focused contract to verify GREEN**

Run from the repository root:

```powershell
$files = @(
  'source/app/bred/gpu/layer.h',
  'source/app/bred/gpu/layer.cpp',
  'source/app/bred/gpu/graphics.h',
  'source/app/bred/gpu/graphics.cpp',
  'source/app/bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp')
foreach ($file in $files) {
  $path = Resolve-Path $file
  $text = [System.IO.File]::ReadAllText($path)
  $text = $text -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
Set-Location source/app
g++ bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract failed' }
```

Expected: the focused contract exits with code `0`.

- [ ] **Step 7: Commit the composition-intent boundary**

```powershell
git -C source/app add -- bred/gpu/layer.h bred/gpu/layer.cpp bred/gpu/graphics.h bred/gpu/graphics.cpp bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp
git -C source/app diff --cached --check
git -C source/app commit -m "feat: mark memory-image GPU layers non-composited"
```

Expected: one focused `source/app` commit; unrelated changes remain unstaged.

---

### Task 2: Filter the final frame merge by layer composition intent

**Files:**
- Modify: `source/app/bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp`
- Modify: `source/app/bred/gpu/renderer.cpp:1669-1796`

**Interfaces:**
- Consumes: Task 1's `gpu::layer::m_bIncludeInFrameComposition`
- Produces: local `gpulayera` containing only layers enabled for automatic frame composition
- Preserves: `gpu::device::m_pgpulayera` as the complete layer-lifecycle array

- [ ] **Step 1: Extend the contract for consistent closing-layer filtering**

Add these reads after `graphicsSource` in the test's `main`:

```cpp
   const auto rendererSource = read_file("bred/gpu/renderer.cpp");
```

Add these assertions before `return 0`:

```cpp
   const auto rendererEndLayer = section(
      rendererSource,
      "void renderer::end_layer(bool bClosingLayer)",
      "void renderer::wait_swap_chain_command_buffer_ready()");
   const auto layerArraySnapshot = rendererEndLayer.find(
      "auto pgpulayera2 = m_pgpucontext->m_pgpudevice->m_pgpulayera;");
   const auto filterLoop = rendererEndLayer.find(
      "for (auto pgpulayer : *pgpulayera2)",
      layerArraySnapshot);
   const auto filterPredicate = rendererEndLayer.find(
      "pgpulayer->m_bIncludeInFrameComposition",
      filterLoop);
   const auto filteredAdd = rendererEndLayer.find(
      "gpulayera.add(pgpulayer);",
      filterPredicate);
   const auto completionWait = rendererEndLayer.find(
      "for (auto pgpulayer: gpulayera)",
      filteredAdd);
   const auto merge = rendererEndLayer.find(
      "merge_layers(pgpucommandbuffer, ptextureBackBuffer, &gpulayera);",
      completionWait);
   const auto semaphoreLoop = rendererEndLayer.find(
      "for (auto &pgpulayer: gpulayera)",
      merge);

   assert(layerArraySnapshot != std::string::npos);
   assert(filterLoop != std::string::npos);
   assert(filterPredicate != std::string::npos);
   assert(filteredAdd != std::string::npos);
   assert(completionWait != std::string::npos);
   assert(merge != std::string::npos);
   assert(semaphoreLoop != std::string::npos);
   assert(layerArraySnapshot < filterLoop);
   assert(filterLoop < filterPredicate);
   assert(filterPredicate < filteredAdd);
   assert(filteredAdd < completionWait);
   assert(completionWait < merge);
   assert(merge < semaphoreLoop);
   assert(rendererEndLayer.find("gpulayera = *pgpulayera2;") ==
      std::string::npos);
   assert(rendererEndLayer.find("e_output_gpu_buffer") ==
      std::string::npos);
```

- [ ] **Step 2: Run the extended contract to verify RED**

Run from `source/app`:

```powershell
g++ bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
```

Expected: the executable aborts because `renderer::end_layer` still copies the complete device layer array directly.

- [ ] **Step 3: Derive the filtered composition list**

In `renderer::end_layer`, replace:

```cpp
            gpulayera = *pgpulayera2;
```

with:

```cpp
            for (auto pgpulayer : *pgpulayera2)
            {

               if (pgpulayer
                  && pgpulayer->m_bIncludeInFrameComposition)
               {

                  gpulayera.add(pgpulayer);

               }

            }
```

Leave the device's `m_pgpulayera` unchanged. Existing downstream waits, `merge_layers`, and semaphore collection already consume the local `gpulayera`; do not introduce a second list or refer back to the full array in those operations.

- [ ] **Step 4: Preserve CRLF and run the focused contract to verify GREEN**

Run from the repository root:

```powershell
$files = @(
  'source/app/bred/gpu/renderer.cpp',
  'source/app/bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp')
foreach ($file in $files) {
  $path = Resolve-Path $file
  $text = [System.IO.File]::ReadAllText($path)
  $text = $text -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
Set-Location source/app
g++ bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_memory_image_layer_composition_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract failed' }
```

Expected: the focused contract exits with code `0`.

- [ ] **Step 5: Run focused and neighboring GPU lifecycle contracts**

Run from `source/app`:

```powershell
$tests = @(
  'gpu_memory_image_layer_composition_contract_test',
  'gpu_graphics_layer_scope_contract_test',
  'device_frame_layer_reset_test',
  'context_lease_pool_contract_test')
foreach ($test in $tests) {
  g++ "bred/gpu/tests/$test.cpp" -std=c++17 -o "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "compile failed: $test" }
  & "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "contract failed: $test" }
}
```

Expected: all four executables exit with code `0`.

- [ ] **Step 6: Run neighboring NanoVG image and lease contracts**

Run from `source/app-graphics3d`:

```powershell
$tests = @(
  'gpu_image_wrapper_cache_contract_test',
  'gpu_image_lifecycle_test',
  'graphics_lease_integration_contract_test',
  'memory_graphics_lifecycle_test')
foreach ($test in $tests) {
  g++ "draw2d_nanovg/tests/$test.cpp" -std=c++17 -o "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "compile failed: $test" }
  & "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "contract failed: $test" }
}
```

Expected: all four executables exit with code `0`; the GPU-only image path, wrapper lifetime, and graphics-lease lifecycle remain unchanged.

- [ ] **Step 7: Build the affected Debug x64 targets**

Run from the repository root:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe'
& $msbuild solution-windows\SceneFoundry.sln /t:bred /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'bred build failed' }
& $msbuild solution-windows\SceneFoundry.sln /t:draw2d_nanovg /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'draw2d_nanovg build failed' }
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'shared_app_graphics3d_continuum build failed' }
```

Expected: all three targets finish with `0 Error(s)`.

- [ ] **Step 8: Review and commit the final-composition filter**

```powershell
git -C source/app diff --check -- bred/gpu/renderer.cpp bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp
git -C source/app diff -- bred/gpu/renderer.cpp bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp
git -C source/app add -- bred/gpu/renderer.cpp bred/gpu/tests/gpu_memory_image_layer_composition_contract_test.cpp
git -C source/app diff --cached --check
git -C source/app commit -m "fix: exclude memory-image layers from frame composition"
```

Expected: one focused `source/app` commit containing the filter and completed contract; unrelated changes remain unstaged.

---

### Task 3: Validate first-use font-preview placement at runtime

**Files:**
- Inspect only: Visual Studio Output and the running `shared_app_graphics3d_continuum.exe`

**Interfaces:**
- Consumes: lazy normal and hover font-preview cache generation
- Produces: runtime evidence that offscreen cache rendering is no longer automatically composited

- [ ] **Step 1: Run the reproducing configuration**

Run Debug x64 `shared_app_graphics3d_continuum` from Visual Studio with OpenGL, swap-chain/on-screen rendering, and `draw2d_nanovg`.

Expected: font enumeration completes, the 3D scene and 2D GUI compose normally, and the font list is scrollable.

- [ ] **Step 2: Exercise uncached normal previews**

Scroll into multiple font-list regions that have not previously been visible during this process run.

Expected: each newly generated normal preview appears only inside its intended list rectangle. No same-shaped preview text appears once at window position `(0,0)`, and no black rectangle reappears.

- [ ] **Step 3: Exercise uncached hover previews**

Hover a font whose enlarged preview has not yet been generated, move away, and repeat with several new fonts.

Expected: every large preview appears only at its intended hover rectangle with the translucent background. No large preview appears once at `(0,0)`.

- [ ] **Step 4: Revisit cached previews and validate composition stability**

Scroll back to previously visited rows and hover previously visited fonts while the 3D scene continues rendering.

Expected: cached previews remain correctly placed and responsive; the main 2D GUI and 3D scene remain visible and correctly layered.

- [ ] **Step 5: Close normally**

Close the application after exercising both new and cached previews.

Expected: no OpenGL validation exception, layer-ordering error, message box, or shutdown crash.
