# NanoVG Font Preview Target Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime-controlled evidence that identifies the active WGL context and OpenGL framebuffer when NanoVG flushes a lazily generated GPU-backed font preview.

**Architecture:** Reserve one existing rendered-image diagnostic index before target binding, capture the pre-bind framebuffer, bind the selected target, and emit one correlated target-state line immediately before `nvgEndFrame`. Reuse that same index for the existing post-flush pixel diagnostic so context, framebuffer, and texture contents describe one render event.

**Tech Stack:** C++20, NanoVG GL3, OpenGL/WGL, SceneFoundry GPU image lifecycle, source-contract executables, Visual Studio/MSBuild Debug x64.

## Global Constraints

- The change is diagnostic only; do not alter rendering, cache invalidation, synchronization, target selection, or presentation behavior.
- Confine production-code changes to `source/app-graphics3d/draw2d_nanovg`.
- Keep all output behind the existing public GPU performance diagnostics setting and its generation counter.
- Reuse the existing first-eight rendered-image event budget.
- Preserve non-Windows compilation with WGL-specific code inside `#if defined(WINDOWS_DESKTOP)`.
- Preserve CRLF line endings in modified C++ source and test files.
- Do not modify or stage unrelated worktree changes.

---

### Task 1: Correlate NanoVG target state with rendered image contents

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h:141-151`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:1-45`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:8365-8507`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:9439-9475`

**Interfaces:**
- Consumes: `m_papplication->m_gpu.m_bPerformanceDiagnostics`
- Consumes: `m_papplication->m_gpu.m_uPerformanceDiagnosticsGeneration`
- Consumes: `::gpu_opengl::texture::bind_render_target()` and `frame_buffer_object()`
- Consumes on Windows: `::gpu_opengl::wgl_context::m_hglrc`, `m_hdc`, `wglGetCurrentContext()`, and `wglGetCurrentDC()`
- Produces: `::i64 graphics::reserve_rendered_gpu_image_diagnostic()` returning `-1` when disabled/exhausted or an index in `[0, 7]`
- Produces: `void graphics::diagnose_gpu_image_target_state(...)` emitting `stage=target_state`
- Changes: `diagnose_rendered_gpu_image(texture *, ::i64)` consumes the reserved index instead of allocating another index

- [ ] **Step 1: Write the failing target-state contract**

Extend `gpu_image_boundary_diagnostics_contract_test.cpp` after the existing stage assertions with:

```cpp
   assert(header.find("reserve_rendered_gpu_image_diagnostic()") !=
      std::string::npos);
   assert(header.find("diagnose_gpu_image_target_state(") !=
      std::string::npos);
   const auto renderedDiagnosticDeclaration = header.find(
      "void diagnose_rendered_gpu_image(");
   assert(renderedDiagnosticDeclaration != std::string::npos);
   assert(header.find("::i64 iDiagnosticIndex", renderedDiagnosticDeclaration) !=
      std::string::npos);

   assert(source.find(
      "[gpu.performance.nanovg_image_boundary] stage=target_state") !=
      std::string::npos);
   assert(source.find("wglGetCurrentContext()") != std::string::npos);
   assert(source.find("wglGetCurrentDC()") != std::string::npos);
   assert(source.find("GL_DRAW_FRAMEBUFFER_BINDING") != std::string::npos);
   assert(source.find("GL_VIEWPORT") != std::string::npos);
   assert(source.find("context_match=") != std::string::npos);
   assert(source.find("framebuffer_match=") != std::string::npos);
```

Extend the existing `onEndLayer` ordering block with:

```cpp
   const auto reserveDiagnostic = onEndLayer.find(
      "reserve_rendered_gpu_image_diagnostic()");
   const auto readFramebufferBefore = onEndLayer.find(
      "GL_DRAW_FRAMEBUFFER_BINDING", reserveDiagnostic);
   const auto diagnoseTargetState = onEndLayer.find(
      "diagnose_gpu_image_target_state(", bindTarget);
   const auto endFrameWithDiagnostic = onEndLayer.find(
      "nvgEndFrame(m_pdc);", diagnoseTargetState);
   const auto diagnoseRenderWithIndex = onEndLayer.find(
      "diagnose_rendered_gpu_image(", endFrameWithDiagnostic);
   const auto diagnoseRenderIndex = onEndLayer.find(
      "iDiagnosticIndex", diagnoseRenderWithIndex);
   assert(reserveDiagnostic != std::string::npos);
   assert(readFramebufferBefore != std::string::npos);
   assert(diagnoseTargetState != std::string::npos);
   assert(endFrameWithDiagnostic != std::string::npos);
   assert(diagnoseRenderWithIndex != std::string::npos);
   assert(diagnoseRenderIndex != std::string::npos);
   assert(reserveDiagnostic < readFramebufferBefore);
   assert(readFramebufferBefore < bindTarget);
   assert(bindTarget < diagnoseTargetState);
   assert(diagnoseTargetState < endFrameWithDiagnostic);
   assert(endFrameWithDiagnostic < diagnoseRenderWithIndex);
   assert(diagnoseRenderWithIndex < diagnoseRenderIndex);
```

- [ ] **Step 2: Compile and run the contract to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d`:

```powershell
g++ draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_boundary_diagnostics_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_image_boundary_diagnostics_contract_test.exe"
```

Expected: the executable aborts at the first new assertion because the reservation and target-state diagnostic interfaces do not exist.

- [ ] **Step 3: Declare the diagnostic interfaces**

Replace the rendered diagnostic declaration in `graphics.h` with:

```cpp
      ::i64 reserve_rendered_gpu_image_diagnostic();
      void diagnose_gpu_image_target_state(
         ::i64 iDiagnosticIndex,
         ::gpu::context * pgpucontext,
         ::gpu::layer * pgpulayer,
         ::gpu_opengl::texture * pgputexture,
         ::i32 iDrawFramebufferBefore);
      void diagnose_rendered_gpu_image(
         ::gpu_opengl::texture * pgputexture,
         ::i64 iDiagnosticIndex);
```

Keep the existing sampled-image diagnostic declaration unchanged.

- [ ] **Step 4: Make WGL context identity available only on Windows**

Add this include next to the existing `gpu_opengl` includes in `graphics.cpp`:

```cpp
#if defined(WINDOWS_DESKTOP)
#include "gpu_opengl/wgl_context.h"
#endif
```

- [ ] **Step 5: Reserve the existing rendered-image diagnostic index before binding**

Insert this method immediately before `diagnose_rendered_gpu_image`:

```cpp
   ::i64 graphics::reserve_rendered_gpu_image_diagnostic()
   {

      if (!m_papplication
         || !m_papplication->m_gpu.m_bPerformanceDiagnostics.load(
            ::std::memory_order_relaxed))
      {

         return -1;

      }

      auto uGeneration =
         m_papplication->m_gpu.m_uPerformanceDiagnosticsGeneration.load(
            ::std::memory_order_relaxed);

      if (uGeneration != m_uPerformanceDiagnosticsGenerationLast.load(
         ::std::memory_order_relaxed))
      {

         reset_gpu_image_performance_diagnostics();

      }

      auto uDiagnosticIndex =
         m_uPerformanceRenderedTextureDiagnostics.fetch_add(
            1,
            ::std::memory_order_relaxed);

      if (uDiagnosticIndex >= 8)
      {

         return -1;

      }

      return (::i64)uDiagnosticIndex;

   }
```

- [ ] **Step 6: Add the observational target-state diagnostic**

Insert this method after the reservation method:

```cpp
   void graphics::diagnose_gpu_image_target_state(
      ::i64 iDiagnosticIndex,
      ::gpu::context * pgpucontext,
      ::gpu::layer * pgpulayer,
      ::gpu_opengl::texture * pgputexture,
      ::i32 iDrawFramebufferBefore)
   {

      if (iDiagnosticIndex < 0 || !pgputexture)
      {

         return;

      }

      GLint iDrawFramebufferAfter = 0;
      GLint iaViewport[4]{};
      glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &iDrawFramebufferAfter);
      glGetIntegerv(GL_VIEWPORT, iaViewport);
      auto uTargetFramebuffer = pgputexture->frame_buffer_object();

#if defined(WINDOWS_DESKTOP)
      auto pwglcontext = dynamic_cast < ::gpu_opengl::wgl_context * >(pgpucontext);
      auto hglrcExpected = pwglcontext ? pwglcontext->m_hglrc : nullptr;
      auto hdcExpected = pwglcontext ? pwglcontext->m_hdc : nullptr;
      auto hglrcCurrent = ::wglGetCurrentContext();
      auto hdcCurrent = ::wglGetCurrentDC();
      auto bContextMatch = hglrcExpected && hglrcExpected == hglrcCurrent;
      auto bDeviceContextMatch = hdcExpected && hdcExpected == hdcCurrent;
#else
      auto bContextMatch = true;
      auto bDeviceContextMatch = true;
#endif

      information() << "[gpu.performance.nanovg_image_boundary] stage=target_state"
         << " diagnostic=" << iDiagnosticIndex
         << " graphics=" << (::uptr)this
         << " image=" << (::uptr)m_pimage
         << " context=" << (::uptr)pgpucontext
         << " layer=" << (::uptr)pgpulayer
         << " texture_object=" << (::uptr)pgputexture
         << " texture=" << pgputexture->m_gluTextureID
#if defined(WINDOWS_DESKTOP)
         << " expected_context=" << (::uptr)hglrcExpected
         << " current_context=" << (::uptr)hglrcCurrent
         << " expected_dc=" << (::uptr)hdcExpected
         << " current_dc=" << (::uptr)hdcCurrent
#endif
         << " context_match=" << bContextMatch
         << " dc_match=" << bDeviceContextMatch
         << " framebuffer_before=" << iDrawFramebufferBefore
         << " target_framebuffer=" << uTargetFramebuffer
         << " framebuffer_after=" << iDrawFramebufferAfter
         << " framebuffer_match="
            << (iDrawFramebufferAfter == (GLint)uTargetFramebuffer)
         << " viewport=" << iaViewport[0] << "," << iaViewport[1]
            << "," << iaViewport[2] << "," << iaViewport[3];

   }
```

This method must not throw on a reported mismatch and must remain before `nvgEndFrame` in the caller.

- [ ] **Step 7: Make the post-flush pixel diagnostic consume the reserved index**

Change the signature to:

```cpp
   void graphics::diagnose_rendered_gpu_image(
      ::gpu_opengl::texture * pgputexture,
      ::i64 iDiagnosticIndex)
```

Replace its setting/generation/counter preamble with:

```cpp
      if (!pgputexture || iDiagnosticIndex < 0)
      {

         return;

      }
```

Keep the size check, `read_pixels`, pixel analysis, and `stage=render` output unchanged. Both target-state and rendered-pixel lines now use the same reserved index.

- [ ] **Step 8: Capture state around target binding in `on_end_layer`**

Replace the active sequence from target validation through rendered-image diagnostics with:

```cpp
      auto pgpuimage = dynamic_cast < ::gpu::image * >(m_pimage);
      ::cast < ::gpu_opengl::texture > ptextureDiagnostic =
         pgputextureTarget;
      auto iDiagnosticIndex = pgpuimage && pgpuimage->gpu_texture()
         ? reserve_rendered_gpu_image_diagnostic()
         : -1;
      GLint iDrawFramebufferBefore = 0;

      if (iDiagnosticIndex >= 0)
      {

         glGetIntegerv(
            GL_DRAW_FRAMEBUFFER_BINDING,
            &iDrawFramebufferBefore);

      }

      pgputextureTarget->bind_render_target();
      diagnose_gpu_image_target_state(
         iDiagnosticIndex,
         pgpucontext,
         pgpulayer,
         ptextureDiagnostic,
         iDrawFramebufferBefore);
      nvgEndFrame(m_pdc);

      if (pgpuimage && pgpuimage->gpu_texture())
      {

         diagnose_rendered_gpu_image(
            ptextureDiagnostic,
            iDiagnosticIndex);
         pgpuimage->gpu_texture()->defer_fence();

      }
```

Retain the existing missing-target exception, `glFlush`, OpenGL error check, and `m_bHadEndLayer` assignment.

- [ ] **Step 9: Preserve CRLF and inspect the focused diff**

Run from the repository root:

```powershell
$files = @(
  'source/app-graphics3d/draw2d_nanovg/graphics.h',
  'source/app-graphics3d/draw2d_nanovg/graphics.cpp',
  'source/app-graphics3d/draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp')
foreach ($file in $files) {
  $path = Resolve-Path $file
  $text = [System.IO.File]::ReadAllText($path)
  $text = $text -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
git -C source/app-graphics3d diff --check -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
git -C source/app-graphics3d diff -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
```

Expected: no whitespace errors and no unrelated files in the focused diff.

- [ ] **Step 10: Run the focused and neighboring contracts to verify GREEN**

Run from `source/app-graphics3d`:

```powershell
$tests = @(
  'gpu_image_boundary_diagnostics_contract_test',
  'gpu_image_lifecycle_test',
  'gpu_image_fast_path_test',
  'memory_graphics_lifecycle_test',
  'graphics_lease_integration_contract_test')
foreach ($test in $tests) {
  g++ "draw2d_nanovg/tests/$test.cpp" -std=c++17 -o "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "compile failed: $test" }
  & "$env:TEMP/$test.exe"
  if ($LASTEXITCODE -ne 0) { throw "contract failed: $test" }
}
```

Expected: all five executables exit with code `0`.

- [ ] **Step 11: Build the affected Debug x64 targets**

Run from the repository root:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe'
& $msbuild solution-windows\SceneFoundry.sln /t:draw2d_nanovg /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'draw2d_nanovg build failed' }
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'shared_app_graphics3d_continuum build failed' }
```

Expected: both targets finish with `0 Error(s)`.

- [ ] **Step 12: Commit only the diagnostic implementation**

```powershell
git -C source/app-graphics3d add -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_boundary_diagnostics_contract_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "diagnostics: trace NanoVG preview target state"
```

Expected: one focused `source/app-graphics3d` commit; unrelated changes remain unstaged.

---

### Task 2: Capture one lazy normal preview and one lazy hover preview

**Files:**
- Inspect only: Visual Studio Output from `shared_app_graphics3d_continuum.exe`

**Interfaces:**
- Consumes: `graphics3d::engine::set_gpu_performance_diagnostics(bool)`
- Produces: correlated `stage=target_state`, `stage=render`, and `stage=sample` runtime evidence

- [ ] **Step 1: Run the reproducing configuration**

Run Debug x64 `shared_app_graphics3d_continuum` in Visual Studio with OpenGL, swap-chain/on-screen rendering, and `draw2d_nanovg`.

Expected: font enumeration completes and the font list opens.

- [ ] **Step 2: Rearm diagnostics before uncached previews**

Call through the public engine setting immediately before scrolling to rows that have not yet appeared:

```cpp
pengine->set_gpu_performance_diagnostics(false);
pengine->set_gpu_performance_diagnostics(true);
```

Expected: the diagnostic generation changes and the first-eight-event budget resets.

- [ ] **Step 3: Reproduce one normal and one hover cache creation**

Scroll until a new row first becomes visible, then hover a font whose enlarged preview has not previously appeared.

Expected: each first render produces a `stage=target_state` line followed by the same-index `stage=render` line; sampling produces `stage=sample` lines for the preview textures.

- [ ] **Step 4: Classify the failing boundary**

Interpret the logged booleans:

- `context_match=false`: NanoVG is flushing while a different WGL context is current.
- `context_match=true framebuffer_match=false`: the expected context is current, but target binding did not select the image framebuffer.
- both matches `true` with transparent/black `stage=render` pixels: the failure is inside NanoVG draw state or font paint rather than context/target selection.
- both matches `true` with correct `stage=render` pixels but a black window rectangle: cache generation is correct and the failure is in GPU-image sampling/composition.

Retain the correlated lines for the next root-cause hypothesis. Do not change rendering behavior until this evidence selects one boundary.
