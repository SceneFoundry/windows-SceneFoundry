# Offscreen Render Loop FPS Throttling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limit the CPU-buffer graphics3d render loop to a runtime-adjustable desired FPS, defaulting safely to 60 FPS.

**Architecture:** Add a small header-only deadline pacer that uses `std::chrono::steady_clock` and can be tested without a GPU or real sleeping. Expose an atomic desired-FPS setting on `graphics3d::engine`, then use the pacer around every `run_cpu_buffer()` iteration so rendering time and non-rendering iterations both count toward the frame interval.

**Tech Stack:** C++20, `std::atomic`, `std::chrono::steady_clock`, Visual Studio 18/MSVC, MSBuild, existing `bred` graphics3d framework.

## Global Constraints

- The public engine setting is `std::atomic<::f32> m_fDesiredFps{60.0f}` and is safe to assign while the loop runs.
- Non-finite and non-positive requested FPS values use 60 FPS.
- A runtime FPS change takes effect on the following loop iteration and resets the deadline.
- An overrun resets the following deadline instead of producing catch-up frames.
- Pacing applies to empty-placement and not-yet-loaded iterations as well as rendered frames.
- The swap-chain path is unchanged; only `run_cpu_buffer()` is paced.
- Preserve the user's existing uncommitted frame-lifecycle and backend changes.
- Do not create implementation commits while `engine.cpp` and `engine.h` contain overlapping pre-existing edits; leave the scoped feature diff for user review.
- Use CRLF line endings for new and modified C++ and Visual Studio project files.

---

### Task 1: Deterministic offscreen frame pacer

**Files:**
- Create: `source/app/bred/graphics3d/offscreen_frame_pacer.h`
- Create: `source/app/bred/graphics3d/tests/offscreen_frame_pacer_tests.cpp`
- Modify: `source/app/bred/bred.vcxproj`
- Modify: `source/app/bred/bred.vcxproj.filters`

**Interfaces:**
- Consumes: Standard-library `std::chrono::steady_clock` and floating-point validation.
- Produces: `graphics3d::offscreen_frame_pacer`, with `begin_frame(time_point, float)`, `should_wait(time_point)`, `deadline()`, `validated_fps(float)`, and `frame_interval(float)`.

- [ ] **Step 1: Write the failing standalone timing test**

Create `source/app/bred/graphics3d/tests/offscreen_frame_pacer_tests.cpp` with deterministic timestamps and no sleeping:

```cpp
#include "../offscreen_frame_pacer.h"

#include <cassert>
#include <chrono>
#include <cmath>
#include <limits>


namespace
{


   using pacer = ::graphics3d::offscreen_frame_pacer;
   using clock = pacer::clock;


   bool approximately_equal(clock::duration left, clock::duration right)
   {

      auto difference = left > right ? left - right : right - left;

      return difference <= std::chrono::microseconds(1);

   }


   void test_default_sixty_fps_interval()
   {

      pacer framepacer;
      auto now = clock::time_point{};
      auto deadline = framepacer.begin_frame(now, 60.0f);

      assert(approximately_equal(deadline - now, std::chrono::duration_cast<clock::duration>(
         std::chrono::duration<double>(1.0 / 60.0))));
      assert(framepacer.should_wait(now + std::chrono::milliseconds(1)));

   }


   void test_runtime_fps_change_resets_deadline()
   {

      pacer framepacer;
      auto start = clock::time_point{};

      framepacer.begin_frame(start, 60.0f);
      assert(framepacer.should_wait(start + std::chrono::milliseconds(5)));

      auto changed = start + std::chrono::milliseconds(10);
      auto deadline = framepacer.begin_frame(changed, 30.0f);

      assert(approximately_equal(deadline - changed, std::chrono::duration_cast<clock::duration>(
         std::chrono::duration<double>(1.0 / 30.0))));

   }


   void test_overrun_resets_instead_of_catching_up()
   {

      pacer framepacer;
      auto start = clock::time_point{};

      framepacer.begin_frame(start, 60.0f);
      auto overrun = start + std::chrono::milliseconds(20);
      assert(!framepacer.should_wait(overrun));

      auto deadline = framepacer.begin_frame(overrun, 60.0f);

      assert(approximately_equal(deadline - overrun, std::chrono::duration_cast<clock::duration>(
         std::chrono::duration<double>(1.0 / 60.0))));

   }


   void test_invalid_fps_uses_sixty_fps()
   {

      assert(pacer::validated_fps(0.0f) == 60.0f);
      assert(pacer::validated_fps(-1.0f) == 60.0f);
      assert(pacer::validated_fps(std::numeric_limits<float>::infinity()) == 60.0f);
      assert(pacer::validated_fps(std::numeric_limits<float>::quiet_NaN()) == 60.0f);

   }


   void test_expired_deadline_does_not_wait()
   {

      pacer framepacer;
      auto start = clock::time_point{};
      auto deadline = framepacer.begin_frame(start, 60.0f);

      assert(framepacer.should_wait(deadline - std::chrono::microseconds(1)));
      assert(!framepacer.should_wait(deadline));

   }


} // namespace


int main()
{

   test_default_sixty_fps_interval();
   test_runtime_fps_change_resets_deadline();
   test_overrun_resets_instead_of_catching_up();
   test_invalid_fps_uses_sixty_fps();
   test_expired_deadline_does_not_wait();

   return 0;

}
```

- [ ] **Step 2: Compile the test and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\graphics3d\tests\offscreen_frame_pacer_tests.cpp /Fo:`"$env:TEMP\offscreen_frame_pacer_tests.obj`" /Fe:`"$env:TEMP\offscreen_frame_pacer_tests.exe`""
```

Expected: compilation fails with MSVC error C1083 because `offscreen_frame_pacer.h` does not exist.

- [ ] **Step 3: Implement the minimal deadline pacer**

Create `source/app/bred/graphics3d/offscreen_frame_pacer.h`:

```cpp
#pragma once


#include <chrono>
#include <cmath>


namespace graphics3d
{


   class offscreen_frame_pacer
   {
   public:


      using clock = std::chrono::steady_clock;
      using duration = clock::duration;
      using time_point = clock::time_point;

      static constexpr float s_fDefaultFps = 60.0f;

      bool m_bInitialized = false;
      bool m_bPreviousFrameOverran = false;
      float m_fAppliedFps = s_fDefaultFps;
      time_point m_timeNextFrame{};


      static float validated_fps(float fDesiredFps) noexcept
      {

         if (!std::isfinite(fDesiredFps) || fDesiredFps <= 0.0f)
         {

            return s_fDefaultFps;

         }

         return fDesiredFps;

      }


      static duration frame_interval(float fDesiredFps) noexcept
      {

         auto fValidatedFps = validated_fps(fDesiredFps);

         return std::chrono::duration_cast<duration>(
            std::chrono::duration<double>(1.0 / static_cast<double>(fValidatedFps)));

      }


      time_point begin_frame(time_point timeNow, float fDesiredFps) noexcept
      {

         auto fValidatedFps = validated_fps(fDesiredFps);
         auto bFpsChanged = !m_bInitialized || fValidatedFps != m_fAppliedFps;

         if (bFpsChanged || m_bPreviousFrameOverran)
         {

            m_timeNextFrame = timeNow + frame_interval(fValidatedFps);

         }
         else
         {

            m_timeNextFrame += frame_interval(fValidatedFps);

         }

         m_bInitialized = true;
         m_bPreviousFrameOverran = false;
         m_fAppliedFps = fValidatedFps;

         return m_timeNextFrame;

      }


      bool should_wait(time_point timeNow) noexcept
      {

         m_bPreviousFrameOverran = timeNow >= m_timeNextFrame;

         return !m_bPreviousFrameOverran;

      }


      time_point deadline() const noexcept
      {

         return m_timeNextFrame;

      }


   };


} // namespace graphics3d
```

- [ ] **Step 4: Add the helper to the Visual Studio project**

Add this entry beside `graphics3d\engine.h` in `source/app/bred/bred.vcxproj`:

```xml
    <ClInclude Include="graphics3d\offscreen_frame_pacer.h" />
```

Add this entry beside `graphics3d\engine.h` in `source/app/bred/bred.vcxproj.filters`:

```xml
    <ClInclude Include="graphics3d\offscreen_frame_pacer.h">
      <Filter>Header Files\graphics3d</Filter>
    </ClInclude>
```

- [ ] **Step 5: Compile and run the deterministic test to verify GREEN**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\graphics3d\tests\offscreen_frame_pacer_tests.cpp /Fo:`"$env:TEMP\offscreen_frame_pacer_tests.obj`" /Fe:`"$env:TEMP\offscreen_frame_pacer_tests.exe`" && `"$env:TEMP\offscreen_frame_pacer_tests.exe`""
```

Expected: MSVC exits 0 and the test executable exits 0 without assertion failures.

- [ ] **Step 6: Inspect the scoped pacer diff without committing unrelated work**

```powershell
git -C source/app diff --check -- bred/bred.vcxproj bred/bred.vcxproj.filters bred/graphics3d/offscreen_frame_pacer.h bred/graphics3d/tests/offscreen_frame_pacer_tests.cpp
git -C source/app status --short -- bred/bred.vcxproj bred/bred.vcxproj.filters bred/graphics3d/offscreen_frame_pacer.h bred/graphics3d/tests/offscreen_frame_pacer_tests.cpp
```

Expected: no whitespace errors and only the four scoped files are listed. Do not commit because implementation will overlap an already dirty framework worktree.

### Task 2: Runtime-adjustable engine setting and loop integration

**Files:**
- Modify: `source/app/bred/graphics3d/engine.h`
- Modify: `source/app/bred/graphics3d/engine.cpp`

**Interfaces:**
- Consumes: `graphics3d::offscreen_frame_pacer` from Task 1.
- Produces: Public `std::atomic<::f32> graphics3d::engine::m_fDesiredFps`, defaulting to `60.0f`; paced `engine::run_cpu_buffer()` behavior.

- [ ] **Step 1: Add the public atomic engine setting**

In `source/app/bred/graphics3d/engine.h`, add the standard atomic include beside `<chrono>`:

```cpp
#include <atomic>
```

Add the setting beside `m_fFrameTime`:

```cpp
      ::std::atomic<::f32>                              m_fDesiredFps{60.0f};
```

Callers can change it while the loop runs with:

```cpp
pengine->m_fDesiredFps = 30.0f;
```

- [ ] **Step 2: Include the pacer and restructure the loop so every iteration reaches pacing**

In `source/app/bred/graphics3d/engine.cpp`, include `offscreen_frame_pacer.h` beside `engine.h`. In the forked procedure inside `run_cpu_buffer()`, construct one pacer before the `while` loop:

```cpp
            ::graphics3d::offscreen_frame_pacer framepacer;

            while (task_get_run())
            {

               auto timeFrameDeadline = framepacer.begin_frame(
                  ::graphics3d::offscreen_frame_pacer::clock::now(),
                  m_fDesiredFps.load(::std::memory_order_relaxed));
```

Replace the two early `continue` blocks and the existing unconditional rendering body with this guarded rendering block, preserving the current frame-lifecycle calls exactly:

```cpp
               task_iteration();

               if (m_rectanglePlacementNew.has_area() && m_bLoadedEngine)
               {

                  auto pcontext = gpu_context();

                  pcontext->set_placement(m_rectanglePlacementNew);

                  auto prenderer = pcontext->get_gpu_renderer();

                  prenderer->defer_update_renderer();

                  auto pcpubuffer = pcontext->get_cpu_buffer();

                  auto pimagetarget = pcpubuffer->get_image_target();

                  if (!pimagetarget->m_callbackOnImagePixels)
                  {

                     pimagetarget->m_callbackOnImagePixels =
                        [this]()
                        {

                           m_pusergraphics3d->set_need_redraw();

                           m_pusergraphics3d->post_redraw();

                        };

                  }

                  try
                  {

                     try
                     {

                        m_pgpucontextCompositor2->m_pgpudevice->start_frame();

                     }
                     catch (...)
                     {


                     }

                     draw_layer();

                  }
                  catch (...)
                  {


                  }

                  auto pdevice = pcontext->m_pgpudevice;

                  pdevice->end_frame();

               }

               auto timeAfterFrame = ::graphics3d::offscreen_frame_pacer::clock::now();

               if (framepacer.should_wait(timeAfterFrame))
               {

                  ::std::this_thread::sleep_until(timeFrameDeadline);

               }
```

Do not move or alter the existing `start_frame()`, `draw_layer()`, or `end_frame()` ordering inside the guarded block. Do not modify the swap-chain `run()` path.

- [ ] **Step 3: Re-run the standalone pacing tests**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\graphics3d\tests\offscreen_frame_pacer_tests.cpp /Fo:`"$env:TEMP\offscreen_frame_pacer_tests.obj`" /Fe:`"$env:TEMP\offscreen_frame_pacer_tests.exe`" && `"$env:TEMP\offscreen_frame_pacer_tests.exe`""
```

Expected: compilation and execution both exit 0.

- [ ] **Step 4: Build `bred` to verify the actual engine API and loop integration**

Run:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild 'source\app\bred\bred.vcxproj' /t:Build /m /p:Configuration=Debug /p:Platform=x64
```

Expected: `Build succeeded`, with 0 compilation errors in `engine.h`, `engine.cpp`, and `offscreen_frame_pacer.h`.

- [ ] **Step 5: Inspect the scoped integration diff without committing pre-existing edits**

```powershell
git -C source/app diff --check -- bred/graphics3d/engine.h bred/graphics3d/engine.cpp
git -C source/app diff -- bred/graphics3d/engine.h bred/graphics3d/engine.cpp
```

Expected: no whitespace errors. Review the full files carefully because both contained pre-existing edits before this feature; do not stage or commit them.

### Task 3: Integration verification and handoff

**Files:**
- Verify only: `source/app/bred/graphics3d/engine.h`
- Verify only: `source/app/bred/graphics3d/engine.cpp`
- Verify only: `source/app-graphics3d/continuum/__implement/shared_app_graphics3d_continuum.vcxproj`

**Interfaces:**
- Consumes: The tested pacer and runtime-adjustable engine setting from Tasks 1 and 2.
- Produces: A freshly built continuum executable ready for the user's OpenGL offscreen runtime memory check.

- [ ] **Step 1: Inspect scoped diffs and line endings**

Run:

```powershell
git -C source/app diff --check
git -C source/app diff --stat
git -C source/app status --short
```

Expected: no whitespace errors; only intended files from this feature plus the user's pre-existing changes are reported. Confirm modified C++ and project files remain CRLF.

- [ ] **Step 2: Run the standalone pacer test freshly**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\graphics3d\tests\offscreen_frame_pacer_tests.cpp /Fo:`"$env:TEMP\offscreen_frame_pacer_tests.obj`" /Fe:`"$env:TEMP\offscreen_frame_pacer_tests.exe`" && `"$env:TEMP\offscreen_frame_pacer_tests.exe`""
```

Expected: exit 0.

- [ ] **Step 3: Build the continuum application and dependencies**

Run:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild 'source\app-graphics3d\continuum\__implement\shared_app_graphics3d_continuum.vcxproj' /t:Build /m /p:Configuration=Debug /p:Platform=x64
```

Expected: `Build succeeded` and `time-windows\x64\Debug\shared_app_graphics3d_continuum.exe` is refreshed.

- [ ] **Step 4: Provide the runtime validation procedure**

Ask the user to run the OpenGL CPU-buffer/offscreen configuration and observe `shared_app_graphics3d_continuum.exe` in Task Manager for at least 60 seconds. At the default setting, frame production should be approximately 60 FPS. Then assign, for example:

```cpp
m_pengine->m_fDesiredFps = 30.0f;
```

and confirm the rate changes on the following iteration without restarting the loop. Record whether private memory stabilizes; do not claim the original memory-growth symptom is fixed until this runtime check is observed.
