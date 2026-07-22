# NanoVG Targeted End-Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure NanoVG flushes each layer exactly once into its explicitly selected window or GPU-image target.

**Architecture:** Keep the correction inside `draw2d_nanovg`. The compositor callback `graphics::on_end_layer` will resolve and bind the current GPU target immediately before the deferred `nvgEndFrame` flush, then diagnose and fence the completed image. The outer `graphics::end_layer` will only delegate into the generic GPU lifecycle.

**Tech Stack:** C++20, NanoVG GL3, OpenGL/WGL, SceneFoundry GPU compositor lifecycle, source-contract executables, Visual Studio/MSBuild Debug x64.

## Global Constraints

- Confine production-code changes to `source/app-graphics3d/draw2d_nanovg`.
- Preserve both on-screen window rendering and offscreen `gpu::image` rendering.
- Preserve CRLF line endings in modified C++ source and test files.
- Do not modify or stage unrelated existing worktree changes.
- Keep `gpu.performance.nanovg_image_boundary` runtime-configurable; add no always-on diagnostic output.

---

### Task 1: Make the compositor callback the single targeted flush boundary

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:9439-9456`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:9734-9950`

**Interfaces:**
- Consumes: `::gpu::context::current_target_texture(::gpu::layer *) -> ::gpu::texture *`
- Consumes: virtual `::gpu::texture::bind_render_target()`
- Produces: `draw2d_nanovg::graphics::on_end_layer(::gpu::layer *)` as the sole active owner of `nvgEndFrame(m_pdc)`
- Preserves: `draw2d_nanovg::graphics::end_layer(bool)` as the public entry point delegating to `::gpu::graphics::end_layer(bool)`

- [ ] **Step 1: Extend the lifecycle contract with target and flush ordering**

Replace the existing `on_end_layer` assertion block in `gpu_image_lifecycle_test.cpp` with:

```cpp
   const auto onEndLayer = section(
      graphicsSource,
      "void graphics::on_end_layer(",
      "void graphics::start_layer(");
   const auto resolveTarget = onEndLayer.find(
      "current_target_texture(pgpulayer)");
   const auto requireTarget = onEndLayer.find(
      "if (!pgputextureTarget)", resolveTarget);
   const auto bindTarget = onEndLayer.find(
      "pgputextureTarget->bind_render_target();", requireTarget);
   const auto endFrame = onEndLayer.find(
      "nvgEndFrame(m_pdc);", bindTarget);
   const auto diagnoseRender = onEndLayer.find(
      "diagnose_rendered_gpu_image(", endFrame);
   const auto imageFence = onEndLayer.find(
      "defer_fence();", endFrame);
   assert(resolveTarget != std::string::npos);
   assert(requireTarget != std::string::npos);
   assert(bindTarget != std::string::npos);
   assert(endFrame != std::string::npos);
   assert(diagnoseRender != std::string::npos);
   assert(imageFence != std::string::npos);
   assert(resolveTarget < requireTarget);
   assert(requireTarget < bindTarget);
   assert(bindTarget < endFrame);
   assert(endFrame < diagnoseRender);
   assert(endFrame < imageFence);

   const auto publicEndLayer = section(
      graphicsSource,
      "void graphics::end_layer(bool bClosingLayer)",
      "void graphics::on_present()");
   assert(publicEndLayer.find("nvgEndFrame(m_pdc);") == std::string::npos);
   assert(publicEndLayer.find("diagnose_rendered_gpu_image(") ==
      std::string::npos);
   assert(publicEndLayer.find(
      "::gpu::graphics::end_layer(bClosingLayer);") != std::string::npos);
```

- [ ] **Step 2: Move the diagnostic-order contract to `on_end_layer`**

Add this helper inside the anonymous namespace in `gpu_image_boundary_diagnostics_contract_test.cpp`:

```cpp
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
```

Replace the existing end-frame ordering assertions with:

```cpp
   const auto onEndLayer = section(
      source,
      "void graphics::on_end_layer(",
      "void graphics::start_layer(");
   const auto bindTarget = onEndLayer.find(
      "pgputextureTarget->bind_render_target();");
   const auto endFrame = onEndLayer.find(
      "nvgEndFrame(m_pdc);", bindTarget);
   const auto gpuImageGuard = onEndLayer.find(
      "dynamic_cast < ::gpu::image * >(m_pimage)", endFrame);
   const auto diagnoseRender = onEndLayer.find(
      "diagnose_rendered_gpu_image(", gpuImageGuard);
   assert(bindTarget != std::string::npos);
   assert(endFrame != std::string::npos);
   assert(gpuImageGuard != std::string::npos);
   assert(diagnoseRender != std::string::npos);
   assert(bindTarget < endFrame);
   assert(endFrame < gpuImageGuard);
   assert(gpuImageGuard < diagnoseRender);

   const auto publicEndLayer = section(
      source,
      "void graphics::end_layer(bool bClosingLayer)",
      "void graphics::on_present()");
   assert(publicEndLayer.find("nvgEndFrame(m_pdc);") == std::string::npos);
   assert(publicEndLayer.find("diagnose_rendered_gpu_image(") ==
      std::string::npos);
   assert(publicEndLayer.find(
      "::gpu::graphics::end_layer(bClosingLayer);") != std::string::npos);
```

- [ ] **Step 3: Run the contracts and observe the pre-implementation failure**

Run from `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d`:

```powershell
g++ draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_lifecycle_test.exe"
& "$env:TEMP/gpu_image_lifecycle_test.exe"
g++ draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_boundary_diagnostics_contract_test.exe"
& "$env:TEMP/gpu_image_boundary_diagnostics_contract_test.exe"
```

Expected: both abort on assertions because `on_end_layer` does not bind the target and public `end_layer` still owns another `nvgEndFrame` call.

- [ ] **Step 4: Implement the single targeted flush in `graphics::on_end_layer`**

Replace its active body with the following sequence, retaining existing comments after the active body:

```cpp
      auto pgpucontext = gpu_context();
      auto pgputextureTarget = pgpucontext
         ? pgpucontext->current_target_texture(pgpulayer)
         : nullptr;

      if (!pgputextureTarget)
      {

         throw ::exception(
            error_wrong_state,
            "NanoVG has no current GPU target at the end-frame flush boundary.");

      }

      pgputextureTarget->bind_render_target();
      nvgEndFrame(m_pdc);

      auto pgpuimage = dynamic_cast < ::gpu::image * >(m_pimage);

      if (pgpuimage && pgpuimage->gpu_texture())
      {

         ::cast < ::gpu_opengl::texture > ptextureDiagnostic =
            pgputextureTarget;

         diagnose_rendered_gpu_image(ptextureDiagnostic);
         pgpuimage->gpu_texture()->defer_fence();

      }

      glFlush();
      ::opengl::check_error("");

      m_bHadEndLayer = true;
```

- [ ] **Step 5: Remove the duplicate public flush and diagnostic**

Delete the active `if (!m_bHadEndLayer) { nvgEndFrame(m_pdc); }` block and the following `pgpuimageDiagnostic` block from `graphics::end_layer`. Retain:

```cpp
      ::gpu::graphics::end_layer(bClosingLayer);
```

- [ ] **Step 6: Preserve CRLF and inspect only the focused diff**

Run from the repository root:

```powershell
$files = @('source/app-graphics3d/draw2d_nanovg/graphics.cpp', 'source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp', 'source/app-graphics3d/draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp')
foreach ($file in $files) { $path = Resolve-Path $file; $text = [System.IO.File]::ReadAllText($path); $text = $text -replace "`r?`n", "`r`n"; [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false)) }
git -C source/app-graphics3d diff --check -- draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
git -C source/app-graphics3d diff -- draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
```

Expected: no whitespace errors; the diff contains only the target bind, single-flush relocation, diagnostic relocation, and matching contract changes.

- [ ] **Step 7: Run all focused and neighboring NanoVG contracts**

Run from `source/app-graphics3d`:

```powershell
$tests = @('gpu_image_lifecycle_test', 'gpu_image_boundary_diagnostics_contract_test', 'gpu_image_fast_path_test', 'memory_graphics_lifecycle_test', 'graphics_lease_integration_contract_test')
foreach ($test in $tests) { g++ "draw2d_nanovg/tests/$test.cpp" -std=c++17 -o "$env:TEMP/$test.exe"; if ($LASTEXITCODE -ne 0) { throw "compile failed: $test" }; & "$env:TEMP/$test.exe"; if ($LASTEXITCODE -ne 0) { throw "contract failed: $test" } }
```

Expected: all five executables exit with code `0`.

- [ ] **Step 8: Build the affected Debug x64 solution targets**

Run from the repository root:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild solution-windows\SceneFoundry.sln /t:draw2d_nanovg /m /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false
if ($LASTEXITCODE -ne 0) { throw 'draw2d_nanovg build failed' }
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false
if ($LASTEXITCODE -ne 0) { throw 'shared_app_graphics3d_continuum build failed' }
```

Expected: both targets finish with `0 Error(s)`.

- [ ] **Step 9: Commit only the focused subrepository changes**

```powershell
git -C source/app-graphics3d add -- draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "fix: target NanoVG end-frame flush"
```

Expected: one `source/app-graphics3d` commit; unrelated files remain unstaged.

---

### Task 2: Perform runtime font-preview validation

**Files:**
- Inspect only: runtime output from `shared_app_graphics3d_continuum.exe`

**Interfaces:**
- Consumes: corrected `draw2d_nanovg::graphics::on_end_layer`
- Produces: runtime evidence that cache generation and window composition select their intended targets

- [ ] **Step 1: Run the application using on-screen OpenGL and `draw2d_nanovg`**

Start `shared_app_graphics3d_continuum` from Visual Studio with the configuration that reproduced the problem.

Expected: font enumeration finishes without a NanoVG font-loading exception.

- [ ] **Step 2: Validate normal cached previews**

Open the font list and inspect multiple rows before and after scrolling.

Expected: every visible row contains its font sample instead of a black rectangle, and scrolling remains responsive.

- [ ] **Step 3: Validate the hover preview**

Hover several font names with visibly different typefaces.

Expected: the large font name and translucent gray background appear together at the intended hover rectangle. No duplicate preview appears at window coordinate `(0,0)`.

- [ ] **Step 4: Capture boundary evidence only if the visual result is still wrong**

If a preview remains incorrect, enable the existing GPU performance diagnostic, reset its generation after enumeration, hover one font, and capture lines beginning with:

```text
[gpu.performance.nanovg_image_boundary]
```

Expected after the correction: the relevant `stage=render` texture reports nonzero alpha and/or RGB pixels, and the matching `stage=sample` line reports the intended nonzero hover target rectangle.
