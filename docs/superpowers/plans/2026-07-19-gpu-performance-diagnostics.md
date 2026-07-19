# Runtime GPU Performance Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add permanent runtime-configurable measurements that identify whether font-list stalls come from preview generation, CPU image transfers, OpenGL fence waits, or repeated NanoVG texture wrapping.

**Architecture:** Application GPU settings are the shared runtime source of truth because font-list and draw2d contexts can exist outside direct graphics3d-engine ownership. Each instrumented object keeps interval counters and reports tagged deltas; disabled diagnostics take one relaxed flag load and perform no timing, allocation, or formatting.

**Tech Stack:** C++20, `std::atomic`, `std::chrono::steady_clock`, SceneFoundry `acme`/`aura`/`bred`, OpenGL, NanoVG GL3, MSVC/Visual Studio, source-level contract tests.

## Global Constraints

- Preserve existing line endings when practical; use Windows CRLF for modified C++ sources and new C++ tests.
- Preserve unrelated dirty work in the root, `source/app`, and `source/app-graphics3d` repositories.
- Diagnostics default to disabled; the default report interval is 1,000 milliseconds.
- Clamp report intervals to the inclusive range from 100 through 60,000 milliseconds.
- Runtime setting changes take effect without restarting rendering.
- Disabled hot paths perform one relaxed enabled-flag load and no clock reads, counter updates, allocations, or formatting.
- Count only actual GPU-image map/unmap state transitions.
- Emit at most 64 detailed map/unmap transition messages after each enable operation.
- Use tags `gpu.performance.font_list`, `gpu.performance.nanovg_image`, and `gpu.performance.image_mapping`.
- Add diagnostics only: do not reorder visibility checks, cache NanoVG handles, change synchronization, or change rendering.
- Stop Continuum gracefully before rebuilding affected DLLs.

---

## File Structure

- `source/app/acme/platform/application.h`: shared atomic settings.
- `source/app/bred/graphics3d/engine.h/.cpp`: public runtime control API.
- `source/app/bred/gpu/image.h/.cpp`: mapping generations and transfer measurements.
- `source/app/gpu_opengl/texture.h/.cpp`: pending-fence query.
- `source/app-graphics3d/draw2d_nanovg/graphics.h/.cpp`: fast-path, fallback, fence, and wrapper measurements.
- `source/app/aura/graphics/write_text/font_list.h/.cpp`: preview-generation and cached-draw measurements.
- Focused source contract tests beside the affected components.

### Task 1: Shared runtime settings and engine API

**Files:**
- Modify: `source/app/acme/platform/application.h`
- Modify: `source/app/bred/graphics3d/engine.h`
- Modify: `source/app/bred/graphics3d/engine.cpp`
- Create: `source/app/bred/graphics3d/tests/gpu_performance_settings_contract_test.cpp`

**Interfaces:**
- Consumes: `platform::application::m_gpu`.
- Produces: `set_gpu_performance_diagnostics(bool)`, `gpu_performance_diagnostics_enabled() const`, `set_gpu_performance_diagnostics_interval(::i32)`, and `gpu_performance_diagnostics_interval() const`.

- [ ] **Step 1: Write the failing settings contract test**

Create a standalone source test with these includes and helper before the assertions:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


std::string read_file(const char * pszPath)
{
   std::ifstream stream(pszPath, std::ios::binary);
   return {
      std::istreambuf_iterator<char>(stream),
      std::istreambuf_iterator<char>()};
}
```

Use this exact `main`:

```cpp
int main()
{
   const auto applicationHeader = read_file("acme/platform/application.h");
   const auto engineHeader = read_file("bred/graphics3d/engine.h");
   const auto engineSource = read_file("bred/graphics3d/engine.cpp");

   assert(applicationHeader.find(
      "::std::atomic_bool m_bPerformanceDiagnostics{false};") != std::string::npos);
   assert(applicationHeader.find(
      "::std::atomic<::i32> m_iPerformanceDiagnosticsIntervalMilliseconds{1000};") != std::string::npos);
   assert(engineHeader.find(
      "void set_gpu_performance_diagnostics(bool bEnabled);") != std::string::npos);
   assert(engineHeader.find(
      "bool gpu_performance_diagnostics_enabled() const;") != std::string::npos);
   assert(engineHeader.find(
      "void set_gpu_performance_diagnostics_interval(::i32 iMilliseconds);") != std::string::npos);
   assert(engineHeader.find(
      "::i32 gpu_performance_diagnostics_interval() const;") != std::string::npos);
   assert(engineSource.find("maximum(100, minimum(60'000, iMilliseconds))") != std::string::npos);
   assert(engineSource.find("::std::memory_order_relaxed") != std::string::npos);
   return 0;
}
```

- [ ] **Step 2: Run RED**

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cd /d C:\Users\camilo\SceneFoundry\main\source\app && cl.exe /nologo /std:c++20 /EHsc bred\graphics3d\tests\gpu_performance_settings_contract_test.cpp /Fe:`"$env:TEMP\gpu_performance_settings_contract_test.exe`" && `"$env:TEMP\gpu_performance_settings_contract_test.exe`""
```

Expected: compilation succeeds and the executable aborts because the API is absent.

- [ ] **Step 3: Add shared settings**

Add `<atomic>` to `application.h` and add to `application::gpu_t`:

```cpp
         ::std::atomic_bool                            m_bPerformanceDiagnostics{false};
         ::std::atomic<::i32>                          m_iPerformanceDiagnosticsIntervalMilliseconds{1000};
```

- [ ] **Step 4: Add the engine methods**

Declare the four produced methods in `engine.h`. Implement them in `engine.cpp` using relaxed loads/stores on `m_papplication->m_gpu`. Both setters throw `error_wrong_state` when `m_papplication` is null. The interval setter uses:

```cpp
      auto iValidatedMilliseconds = maximum(100, minimum(60'000, iMilliseconds));
```

The enabled getter returns `false` and the interval getter returns `1'000` when the application is unavailable.

- [ ] **Step 5: Run GREEN and build**

Run the Step 2 test, then build `acme` and `bred` through `solution-windows/SceneFoundry.sln` with Debug/x64, `/m:1`, `/nr:false`. Expected: all exit `0`.

- [ ] **Step 6: Commit Task 1**

```powershell
git -C source/app add -- acme/platform/application.h bred/graphics3d/engine.h bred/graphics3d/engine.cpp bred/graphics3d/tests/gpu_performance_settings_contract_test.cpp
git -C source/app diff --cached --check
git -C source/app commit -m "Add runtime GPU performance diagnostic settings"
```

### Task 2: GPU-image mapping diagnostics

**Files:**
- Modify: `source/app/bred/gpu/image.h`
- Modify: `source/app/bred/gpu/image.cpp`
- Modify: `source/app/bred/gpu/tests/gpu_image_mapping_contract_test.cpp`

**Interfaces:**
- Consumes: Task 1 settings and existing `map`/`unmap` transfers.
- Produces: per-image map generations, bounded transition records, and `gpu.performance.image_mapping` interval reports.

- [ ] **Step 1: Extend the mapping contract test**

Add assertions after extracting `map` and `unmap` sections:

```cpp
   assert(map.find("if (m_bMapped)") < map.find("m_bPerformanceDiagnostics"));
   assert(unmap.find("if (!m_bMapped)") < unmap.find("m_bPerformanceDiagnostics"));
   assert(imageSource.find("gpu.performance.image_mapping") != std::string::npos);
   assert(imageSource.find("m_uPerformanceMapGeneration") != std::string::npos);
   assert(imageSource.find("current_task_name()") != std::string::npos);
   assert(imageSource.find("s_uMapTransitionSequence.fetch_add") != std::string::npos);
   assert(imageSource.find("< 64") != std::string::npos);
   assert(map.find("read_pixels(pthis);") < map.find("record_performance_map_transition("));
   assert(unmap.find("write_pixels(pthis);") < unmap.find("record_performance_unmap_transition("));
```

- [ ] **Step 2: Run RED**

Compile and run `bred/gpu/tests/gpu_image_mapping_contract_test.cpp` with MSVC. Expected: abort at the first new assertion.

- [ ] **Step 3: Add per-image state and interfaces**

Add `<atomic>`, `<chrono>`, and these mutable members to `gpu::image`:

```cpp
      mutable ::std::atomic_bool m_bPerformanceDiagnosticsEnabledLast{false};
      mutable ::std::atomic<::u64> m_uPerformanceMapGeneration{0};
      mutable ::std::atomic<::u64> m_uPerformanceDetailTransitions{0};
      mutable ::std::atomic<::u64> m_uPerformanceMapTransitions{0};
      mutable ::std::atomic<::u64> m_uPerformanceUnmapTransitions{0};
      mutable ::std::atomic<::u64> m_uPerformanceBytesRead{0};
      mutable ::std::atomic<::u64> m_uPerformanceBytesWritten{0};
      mutable ::std::atomic<::u64> m_uPerformanceReadMicroseconds{0};
      mutable ::std::atomic<::u64> m_uPerformanceWriteMicroseconds{0};
      mutable ::std::atomic<::i64> m_iPerformanceNextReportNanoseconds{0};
```

Declare:

```cpp
      void reset_performance_diagnostics() const;
      void record_performance_map_transition(::u64 uMicroseconds) const;
      void record_performance_unmap_transition(::u64 uMicroseconds) const;
      void report_performance_diagnostics_if_due() const;
```

- [ ] **Step 4: Implement recording and reporting**

Add an anonymous-namespace `::std::atomic<::u64> s_uMapTransitionSequence{0};`. Reset methods zero interval fields and store the next steady-clock deadline as nanoseconds since epoch. Use a compare-exchange on that deadline so only one reporter consumes each interval, then use relaxed exchanges to read and zero counters. Both enabled-state transitions reset counters; false-to-true also resets the 64-message allowance. Map increments the generation; matching unmap keeps it. Compute bytes as `m_sizeRaw.area() * sizeof(::image32_t)`.

For only the first 64 transitions after enable, emit:

```cpp
      information() << "[gpu.performance.image_mapping] transition=" << pszOperation
         << " sequence=" << uSequence
         << " generation=" << m_uPerformanceMapGeneration
         << " image=" << (const void *)this
         << " texture=" << (const void *)m_pgputexture.m_p
         << " size=" << m_sizeRaw
         << " task=" << ::current_task_name();
```

The aggregate report contains `maps`, `unmaps`, `bytes_read`, `bytes_written`, `read_us`, and `write_us`, then resets those deltas.

- [ ] **Step 5: Time only successful real transitions**

Keep the no-op returns before diagnostic flag loads. Inside each context lambda, read the clock only when enabled. Record after successful state transition, preserving:

```cpp
            pgputexture->read_pixels(pthis);
            pthis->pixmap::map(pthis->rectangle());
            pthis->m_bMapped = true;
            pthis->record_performance_map_transition(uMicroseconds);
```

and:

```cpp
            pgputexture->write_pixels(pthis);
            pgputexture->defer_fence();
            pthis->pixmap::unmap();
            pthis->m_bMapped = false;
            pthis->record_performance_unmap_transition(uMicroseconds);
```

- [ ] **Step 6: Run GREEN, build, and commit**

Run `gpu_image_mapping_contract_test`, `gpu_image_contract_test`, and build `bred`. Review the pre-existing context-lock edit, then commit only the three Task 2 files with message `Add GPU image mapping performance diagnostics`.

### Task 3: NanoVG GPU-image and fence diagnostics

**Files:**
- Modify: `source/app/gpu_opengl/texture.h`
- Modify: `source/app/gpu_opengl/texture.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`

**Interfaces:**
- Consumes: Task 1 settings, `gpu_opengl::texture::wait_fence()`, and the existing fast path.
- Produces: `gpu_opengl::texture::has_pending_fence() const` and `gpu.performance.nanovg_image` interval reports.

- [ ] **Step 1: Extend the fast-path test**

Read the OpenGL texture header/source in addition to the NanoVG files and add:

```cpp
   assert(textureHeader.find("bool has_pending_fence() const;") != std::string::npos);
   assert(textureSource.find(
      "return m_glsyncGpuCommandsCompleteFence != nullptr;") != std::string::npos);
   assert(gpuPath.find("has_pending_fence()") < gpuPath.find("wait_fence();"));
   assert(gpuPath.find("record_gpu_image_fast_path(") != std::string::npos);
   assert(source.find("gpu.performance.nanovg_image") != std::string::npos);
   assert(drawRaw.find("record_gpu_image_cpu_fallback();") < cpuMap);
```

Use `..\\app\\gpu_opengl\\texture.h/.cpp` when running from `source/app-graphics3d`.

- [ ] **Step 2: Run RED**

Compile and run `draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`. Expected: abort because the query and counters are absent.

- [ ] **Step 3: Add the pending-fence query**

Declare and implement:

```cpp
   bool texture::has_pending_fence() const
   {
      return m_glsyncGpuCommandsCompleteFence != nullptr;
   }
```

Place the declaration beside `wait_fence()` and the implementation immediately after it.

- [ ] **Step 4: Add per-graphics counters**

Add `<atomic>`, `<chrono>`, and these fields to `draw2d_nanovg::graphics`:

```cpp
      ::std::atomic_bool m_bPerformanceDiagnosticsEnabledLast{false};
      ::std::atomic<::u64> m_uPerformanceGpuImageDraws{0};
      ::std::atomic<::u64> m_uPerformanceCpuFallbackDraws{0};
      ::std::atomic<::u64> m_uPerformanceWrapperCreations{0};
      ::std::atomic<::u64> m_uPerformanceWrapperDeletions{0};
      ::std::atomic<::u64> m_uPerformancePendingFenceWaits{0};
      ::std::atomic<::u64> m_uPerformanceFenceWaitMicroseconds{0};
      ::std::atomic<::u64> m_uPerformanceWrapperMicroseconds{0};
      ::std::atomic<::i64> m_iPerformanceNextReportNanoseconds{0};
```

Declare reset/report helpers plus:

```cpp
      void record_gpu_image_fast_path(
         bool bWaitedForFence,
         ::u64 uFenceMicroseconds,
         ::u64 uWrapperMicroseconds);
      void record_gpu_image_cpu_fallback();
```

- [ ] **Step 5: Instrument one variable at a time**

After texture/device validation, load the enabled setting once. When enabled, query `has_pending_fence()` before `wait_fence()`, and time the wait only when true. Time `nvglCreateImageFromHandleGL3()` and `nvgDeleteImage()` separately, excluding `_draw_nanovg_image()`, and add the two wrapper durations. Call `record_gpu_image_fast_path()` after deletion.

When disabled, preserve the existing calls without clock reads. In `_draw_raw`, call `record_gpu_image_cpu_fallback()` immediately before `pimage->map()` only when enabled. The GPU fast path must still return first.

The interval report contains `gpu_draws`, `cpu_fallbacks`, `wrapper_creates`, `wrapper_deletes`, `pending_fence_waits`, `fence_wait_us`, and `wrapper_us`. Reset counters on both enabled-state transitions and use a compare-exchange deadline plus relaxed counter exchanges for single-consumer interval reporting.

- [ ] **Step 6: Run GREEN and build**

Run the updated fast-path test and build `gpu_opengl` and `draw2d_nanovg`. Expected: all exit `0`.

- [ ] **Step 7: Commit repository boundaries separately**

Commit `gpu_opengl/texture.h/.cpp` in `source/app` with `Expose OpenGL pending texture fences`. Commit the three NanoVG files in `source/app-graphics3d` with `Add NanoVG GPU image performance diagnostics`. Do not stage unrelated WGL work.

### Task 4: Font-list generation and cached-draw diagnostics

**Files:**
- Modify: `source/app/aura/graphics/write_text/font_list.h`
- Modify: `source/app/aura/graphics/write_text/font_list.cpp`
- Create: `source/app/aura/graphics/write_text/tests/font_list_performance_diagnostics_contract_test.cpp`

**Interfaces:**
- Consumes: Task 1 settings and current wide/single-column drawing order.
- Produces: per-font-list `gpu.performance.font_list` reports.

- [ ] **Step 1: Write the failing source contract test**

Create the test with these complete helpers before `main`:

```cpp
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
```

Include `<cassert>`, `<fstream>`, `<iterator>`, and `<string>`, read `font_list.h` into `header` and `font_list.cpp` into `source`, then use these assertions:

```cpp
   assert(header.find("m_uPerformanceDrawPasses") != std::string::npos);
   assert(header.find("m_uPerformanceItemsExamined") != std::string::npos);
   assert(header.find("m_uPerformanceVisibleItems") != std::string::npos);
   assert(header.find("m_uPerformancePreviewUpdates") != std::string::npos);
   assert(header.find("m_uPerformanceCachedDraws") != std::string::npos);
   assert(source.find("gpu.performance.font_list") != std::string::npos);

   const auto wide = section(source,
      "void font_list::_001OnDrawWide(",
      "void font_list::_001OnDrawSingleColumn(");
   const auto single = section(source,
      "void font_list::_001OnDrawSingleColumn(",
      "void font_list::_001OnDraw(");
   assert(wide.find("record_font_item_examined()") != std::string::npos);
   assert(wide.find("record_font_preview_update(") != std::string::npos);
   assert(wide.find("record_cached_font_preview_draw(") != std::string::npos);
   assert(single.find("record_font_item_examined()") != std::string::npos);
   assert(single.find("record_font_preview_update(") != std::string::npos);
   assert(single.find("record_cached_font_preview_draw(") != std::string::npos);
```

- [ ] **Step 2: Run RED**

Compile and run the new test from `source/app`. Expected: abort because fields and calls are absent.

- [ ] **Step 3: Add per-list counters and methods**

Add `<atomic>` and `<chrono>` to `font_list.h`. Add relaxed atomic counters named:

```cpp
      m_uPerformanceDrawPasses
      m_uPerformanceItemsExamined
      m_uPerformanceVisibleItems
      m_uPerformancePreviewUpdates
      m_uPerformanceCachedDraws
      m_uPerformancePreviewUpdateMicroseconds
      m_uPerformanceCachedDrawMicroseconds
```

Also add atomic enabled-state tracking and an atomic nanosecond next-report deadline. Declare:

```cpp
      bool begin_font_list_performance_diagnostics();
      void record_font_item_examined();
      void record_visible_font_item();
      void record_font_preview_update(::u64 uMicroseconds);
      void record_cached_font_preview_draw(::u64 uMicroseconds);
      void report_font_list_performance_diagnostics_if_due();
      void reset_font_list_performance_diagnostics();
```

`begin` performs the one relaxed flag load, handles both enabled-state transitions by resetting counters, increments draw passes, and returns whether timing is active. Record methods use relaxed `fetch_add`. Report claims the deadline with compare-exchange, exchanges interval counters to zero, and emits all seven metrics.

- [ ] **Step 4: Instrument both layouts without fixing them**

Call `begin_font_list_performance_diagnostics()` once at the start of both layout draw functions. In each item loop:

- Record `items_examined` before null/layout/visibility checks.
- Record `visible_items` after the existing intersection succeeds.
- When `is_drawing_ok()` is false, time the existing `pbox->update()` and record an update.
- Otherwise, time `pgraphics->draw(imagedrawing)` and record a cached draw.

Do not move the single-column update below the visibility test. Report before every early return after `begin` and once at normal function exit.

- [ ] **Step 5: Run GREEN, build, and commit**

Run the new test, build `aura`, normalize modified C++ files to CRLF, and commit the three Task 4 files in `source/app` with `Add font list performance diagnostics`.

### Task 5: Integrated verification and evidence run

**Files:**
- Verify: all Task 1-4 files.
- Build: `solution-windows/SceneFoundry.sln`, target `shared_app_graphics3d_continuum`.

**Interfaces:**
- Consumes: all settings and measurements.
- Produces: tagged evidence identifying the dominant scrolling cost.

- [ ] **Step 1: Run all focused tests freshly**

Compile and execute:

```text
bred/graphics3d/tests/gpu_performance_settings_contract_test.cpp
bred/gpu/tests/gpu_image_mapping_contract_test.cpp
bred/gpu/tests/gpu_image_contract_test.cpp
aura/graphics/write_text/tests/font_list_performance_diagnostics_contract_test.cpp
draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
```

Expected: every executable exits `0`.

- [ ] **Step 2: Inspect boundaries and line endings**

Run `git status --short` and `git diff --check` in both nested repositories. Confirm unrelated WGL files remain untouched and modified C++ files are CRLF.

- [ ] **Step 3: Build Continuum**

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe'
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: exit `0` without new compiler or linker errors.

- [ ] **Step 4: Enable and capture**

```cpp
pengine->set_gpu_performance_diagnostics(true);
pengine->set_gpu_performance_diagnostics_interval(1'000);
```

Open the font list, wait for enumeration, scroll continuously for at least ten seconds, and save all three tagged reports.

- [ ] **Step 5: Interpret the dominant metric**

- Growing map/unmap bytes during scrolling identifies CPU fallback.
- High preview updates identifies regeneration.
- High fence wait time identifies unfinished preview-context synchronization.
- High wrapper time with low fence/update time identifies per-draw NanoVG wrapping.
- High examined items with low visible items identifies list traversal/visibility ordering.

Do not implement an optimization until one measurement dominates.

- [ ] **Step 6: Leave root integration unstaged**

Do not stage the root `source` pointer unless the user explicitly requests nested-repository integration after reviewing the runtime evidence.
