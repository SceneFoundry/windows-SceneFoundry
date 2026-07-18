# GPU Post-Frame Context Sampling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore offscreen GPU-to-CPU image publication through a common renderer/context post-frame lifecycle, dispatching every participating context and always invoking `m_pgpucontextMain` last.

**Architecture:** Add a small testable registry that deduplicates frame contexts, remembers each context's latest layer, and performs exception-safe main-last dispatch. `gpu::device` owns that registry, `gpu::context` registers after a layer starts and forwards `on_end_frame()`, and `gpu::renderer` selects CPU sampling from the context output mode before each backend forwards to its existing readback method.

**Tech Stack:** C++20, ca2 `::pointer` ownership, thread-local GPU layers, MSVC/Visual Studio 18, MSBuild, OpenGL, Vulkan, DirectX 11, DirectX 12.

## Global Constraints

- `m_pgpucontextMain` is invoked exactly once and after every participating non-main context.
- Participating non-main contexts retain first-use order and use their most recently registered layer.
- GPU-to-CPU sampling occurs only for `e_output_cpu_buffer`.
- Device synchronization is not held while context callbacks, sampling, or image publication run.
- The previously current thread-local GPU layer is restored even when a callback throws.
- All eligible contexts are attempted; after dispatch, the first captured exception is rethrown.
- Existing backend readback implementations remain intact and are reached through `sample_to_cpu_buffer()`.
- Draw order, swap-chain presentation, GUI callbacks, offscreen FPS pacing, shaders, and cubemap behavior remain unchanged.
- Use CRLF line endings for new and modified C++ and Visual Studio project files.

---

### Task 1: Testable post-frame registry and output policy

**Files:**
- Create: `source/app/bred/gpu/post_frame_context_registry.h`
- Create: `source/app/bred/gpu/tests/post_frame_context_registry_tests.cpp`
- Modify: `source/app/bred/bred.vcxproj:681`
- Modify: `source/app/bred/bred.vcxproj.filters:162`

**Interfaces:**
- Consumes: C++ smart-pointer-like types supporting truth tests and equality.
- Produces: `gpu::post_frame_context_registry<CONTEXT_POINTER, LAYER_POINTER>`, with `clear()`, `register_context()`, `take_entries()`, and static `dispatch()`; `gpu::dispatch_cpu_sampling(bool, SAMPLE&&)`.

- [ ] **Step 1: Write the failing standalone tests**

Create `source/app/bred/gpu/tests/post_frame_context_registry_tests.cpp`:

```cpp
#include "../post_frame_context_registry.h"

#include <cassert>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>


namespace
{


   struct fake_context
   {

      std::string m_strName;
      bool m_bThrow = false;

   };


   struct fake_layer
   {

      int m_iIdentifier = 0;

   };


   using context_pointer = std::shared_ptr<fake_context>;
   using layer_pointer = std::shared_ptr<fake_layer>;
   using registry = ::gpu::post_frame_context_registry<context_pointer, layer_pointer>;


   void test_registration_deduplicates_and_updates_latest_layer()
   {

      registry contextregistry;
      auto pcontextFirst = std::make_shared<fake_context>(fake_context{"first"});
      auto pcontextSecond = std::make_shared<fake_context>(fake_context{"second"});
      auto playerFirst = std::make_shared<fake_layer>(fake_layer{1});
      auto playerFirstLatest = std::make_shared<fake_layer>(fake_layer{2});
      auto playerSecond = std::make_shared<fake_layer>(fake_layer{3});

      contextregistry.register_context(pcontextFirst, playerFirst);
      contextregistry.register_context(pcontextSecond, playerSecond);
      contextregistry.register_context(pcontextFirst, playerFirstLatest);

      auto entrya = contextregistry.take_entries();

      assert(entrya.size() == 2);
      assert(entrya[0].m_pcontext == pcontextFirst);
      assert(entrya[0].m_player == playerFirstLatest);
      assert(entrya[1].m_pcontext == pcontextSecond);
      assert(contextregistry.take_entries().empty());

   }


   void test_dispatch_uses_first_use_order_and_calls_main_last()
   {

      registry contextregistry;
      auto pcontextFirst = std::make_shared<fake_context>(fake_context{"first"});
      auto pcontextMain = std::make_shared<fake_context>(fake_context{"main"});
      auto pcontextSecond = std::make_shared<fake_context>(fake_context{"second"});
      auto playerFirst = std::make_shared<fake_layer>(fake_layer{1});
      auto playerFirstLatest = std::make_shared<fake_layer>(fake_layer{4});
      auto playerMain = std::make_shared<fake_layer>(fake_layer{2});
      auto playerSecond = std::make_shared<fake_layer>(fake_layer{3});
      auto playerPrevious = std::make_shared<fake_layer>(fake_layer{99});
      auto playerCurrent = playerPrevious;
      std::vector<std::string> straCall;

      contextregistry.register_context(pcontextFirst, playerFirst);
      contextregistry.register_context(pcontextMain, playerMain);
      contextregistry.register_context(pcontextSecond, playerSecond);
      contextregistry.register_context(pcontextFirst, playerFirstLatest);

      registry::dispatch(
         contextregistry.take_entries(),
         pcontextMain,
         [&]() { return playerCurrent; },
         [&](const layer_pointer &player) { playerCurrent = player; },
         [&](const context_pointer &pcontext)
         {

            straCall.push_back(
               pcontext->m_strName + ":" + std::to_string(playerCurrent->m_iIdentifier));

         });

      assert((straCall == std::vector<std::string>{"first:4", "second:3", "main:2"}));
      assert(playerCurrent == playerPrevious);

   }


   void test_dispatch_attempts_all_contexts_and_rethrows_first_exception()
   {

      registry contextregistry;
      auto pcontextFirst = std::make_shared<fake_context>(fake_context{"first", true});
      auto pcontextSecond = std::make_shared<fake_context>(fake_context{"second", true});
      auto pcontextMain = std::make_shared<fake_context>(fake_context{"main", false});
      auto player = std::make_shared<fake_layer>(fake_layer{1});
      auto playerPrevious = std::make_shared<fake_layer>(fake_layer{99});
      auto playerCurrent = playerPrevious;
      std::vector<std::string> straCall;

      contextregistry.register_context(pcontextFirst, player);
      contextregistry.register_context(pcontextSecond, player);
      contextregistry.register_context(pcontextMain, player);

      try
      {

         registry::dispatch(
            contextregistry.take_entries(),
            pcontextMain,
            [&]() { return playerCurrent; },
            [&](const layer_pointer &playerSet) { playerCurrent = playerSet; },
            [&](const context_pointer &pcontext)
            {

               straCall.push_back(pcontext->m_strName);

               if (pcontext->m_bThrow)
               {

                  throw std::runtime_error(pcontext->m_strName);

               }

            });

         assert(false);

      }
      catch (const std::runtime_error &error)
      {

         assert(std::string(error.what()) == "first");

      }

      assert((straCall == std::vector<std::string>{"first", "second", "main"}));
      assert(playerCurrent == playerPrevious);

   }


   void test_unregistered_main_is_still_called_last()
   {

      registry contextregistry;
      auto pcontextFirst = std::make_shared<fake_context>(fake_context{"first"});
      auto pcontextMain = std::make_shared<fake_context>(fake_context{"main"});
      auto playerFirst = std::make_shared<fake_layer>(fake_layer{1});
      auto playerPrevious = std::make_shared<fake_layer>(fake_layer{99});
      auto playerCurrent = playerPrevious;
      std::vector<std::string> straCall;

      contextregistry.register_context(pcontextFirst, playerFirst);

      registry::dispatch(
         contextregistry.take_entries(),
         pcontextMain,
         [&]() { return playerCurrent; },
         [&](const layer_pointer &player) { playerCurrent = player; },
         [&](const context_pointer &pcontext)
         {

            straCall.push_back(pcontext->m_strName);

            if (pcontext == pcontextMain)
            {

               assert(!playerCurrent);

            }

         });

      assert((straCall == std::vector<std::string>{"first", "main"}));
      assert(playerCurrent == playerPrevious);

   }


   void test_cpu_sampling_policy()
   {

      int iSampleCount = 0;

      ::gpu::dispatch_cpu_sampling(false, [&]() { ++iSampleCount; });
      assert(iSampleCount == 0);

      ::gpu::dispatch_cpu_sampling(true, [&]() { ++iSampleCount; });
      assert(iSampleCount == 1);

   }


} // namespace


int main()
{

   test_registration_deduplicates_and_updates_latest_layer();
   test_dispatch_uses_first_use_order_and_calls_main_last();
   test_dispatch_attempts_all_contexts_and_rethrows_first_exception();
   test_unregistered_main_is_still_called_last();
   test_cpu_sampling_policy();

   return 0;

}
```

- [ ] **Step 2: Compile the test and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\gpu\tests\post_frame_context_registry_tests.cpp /Fo:`"$env:TEMP\post_frame_context_registry_tests.obj`" /Fe:`"$env:TEMP\post_frame_context_registry_tests.exe`""
```

Expected: compilation fails with MSVC error C1083 because `post_frame_context_registry.h` does not exist.

- [ ] **Step 3: Implement the registry and dispatch policy**

Create `source/app/bred/gpu/post_frame_context_registry.h`:

```cpp
#pragma once


#include <exception>
#include <utility>
#include <vector>


namespace gpu
{


   template < typename CONTEXT_POINTER, typename LAYER_POINTER >
   class post_frame_context_registry
   {
   public:


      struct entry
      {

         CONTEXT_POINTER m_pcontext;
         LAYER_POINTER m_player;

      };


      using entry_array = std::vector<entry>;

      entry_array m_entrya;


      void clear()
      {

         m_entrya.clear();

      }


      void register_context(CONTEXT_POINTER pcontext, LAYER_POINTER player)
      {

         if (!pcontext)
         {

            return;

         }

         for (auto &entry : m_entrya)
         {

            if (entry.m_pcontext == pcontext)
            {

               entry.m_player = std::move(player);

               return;

            }

         }

         m_entrya.push_back({std::move(pcontext), std::move(player)});

      }


      entry_array take_entries()
      {

         return std::exchange(m_entrya, {});

      }


      static LAYER_POINTER find_layer(
         const entry_array &entrya,
         const CONTEXT_POINTER &pcontext)
      {

         for (const auto &entry : entrya)
         {

            if (entry.m_pcontext == pcontext)
            {

               return entry.m_player;

            }

         }

         return {};

      }


      template < typename GET_CURRENT_LAYER, typename SET_CURRENT_LAYER, typename END_CONTEXT >
      static void dispatch(
         entry_array entrya,
         const CONTEXT_POINTER &pcontextMain,
         GET_CURRENT_LAYER getCurrentLayer,
         SET_CURRENT_LAYER setCurrentLayer,
         END_CONTEXT endContext)
      {

         auto playerPrevious = getCurrentLayer();
         std::exception_ptr pexceptionFirst;

         auto invoke =
            [&](const CONTEXT_POINTER &pcontext, const LAYER_POINTER &player)
            {

               try
               {

                  setCurrentLayer(player);
                  endContext(pcontext);

               }
               catch (...)
               {

                  if (!pexceptionFirst)
                  {

                     pexceptionFirst = std::current_exception();

                  }

               }

            };

         for (const auto &entry : entrya)
         {

            if (entry.m_pcontext != pcontextMain)
            {

               invoke(entry.m_pcontext, entry.m_player);

            }

         }

         if (pcontextMain)
         {

            invoke(pcontextMain, find_layer(entrya, pcontextMain));

         }

         try
         {

            setCurrentLayer(playerPrevious);

         }
         catch (...)
         {

            if (!pexceptionFirst)
            {

               pexceptionFirst = std::current_exception();

            }

         }

         if (pexceptionFirst)
         {

            std::rethrow_exception(pexceptionFirst);

         }

      }


   };


   template < typename SAMPLE >
   void dispatch_cpu_sampling(bool bCpuBuffer, SAMPLE &&sample)
   {

      if (bCpuBuffer)
      {

         std::forward<SAMPLE>(sample)();

      }

   }


} // namespace gpu
```

- [ ] **Step 4: Add the production header to the Visual Studio project**

Add beside `gpu\renderer.h` in `source/app/bred/bred.vcxproj`:

```xml
    <ClInclude Include="gpu\post_frame_context_registry.h" />
```

Add beside `gpu\renderer.h` in `source/app/bred/bred.vcxproj.filters`:

```xml
    <ClInclude Include="gpu\post_frame_context_registry.h">
      <Filter>Header Files\gpu</Filter>
    </ClInclude>
```

- [ ] **Step 5: Compile and run the tests to verify GREEN**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\gpu\tests\post_frame_context_registry_tests.cpp /Fo:`"$env:TEMP\post_frame_context_registry_tests.obj`" /Fe:`"$env:TEMP\post_frame_context_registry_tests.exe`" && `"$env:TEMP\post_frame_context_registry_tests.exe`""
```

Expected: compilation and execution both exit 0 without assertion failures.

- [ ] **Step 6: Commit the tested helper**

```powershell
git -C source/app add -- bred/gpu/post_frame_context_registry.h bred/gpu/tests/post_frame_context_registry_tests.cpp bred/bred.vcxproj bred/bred.vcxproj.filters
git -C source/app commit -m "test: add GPU post-frame context registry"
```

Expected: one commit containing only the registry, standalone tests, and project metadata.

### Task 2: Common device, context, and renderer lifecycle

**Files:**
- Modify: `source/app/bred/gpu/device.h:40-92,132-141`
- Modify: `source/app/bred/gpu/device.cpp:1003-1050`
- Modify: `source/app/bred/gpu/context.h:399-414`
- Modify: `source/app/bred/gpu/context.cpp:3869-3880`
- Modify: `source/app/bred/gpu/renderer.h:203-205`
- Modify: `source/app/bred/gpu/renderer.cpp:751`

**Interfaces:**
- Consumes: `gpu::post_frame_context_registry` and `gpu::dispatch_cpu_sampling` from Task 1.
- Produces: `device::register_frame_context(context*, layer*)`, `device::dispatch_post_frame_contexts()`, `context::on_end_frame()`, `renderer::on_end_frame()`, and `renderer::sample_to_cpu_buffer()`.

- [ ] **Step 1: Add the common declarations and registry ownership**

In `source/app/bred/gpu/device.h`, include the helper near the other GPU headers:

```cpp
#include "post_frame_context_registry.h"
```

Inside `gpu::device`, add the registry type and member after `m_framea`:

```cpp
      using post_frame_context_registry_t =
         ::gpu::post_frame_context_registry<
            ::pointer<::gpu::context>,
            ::pointer<::gpu::layer>>;

      post_frame_context_registry_t m_postframecontextregistry;
```

Add these methods beside `start_frame()` and `end_frame()`:

```cpp
      virtual void register_frame_context(::gpu::context *pcontext, ::gpu::layer *player);
      virtual void dispatch_post_frame_contexts();
```

In `source/app/bred/gpu/context.h`, add beside the layer lifecycle declarations:

```cpp
      virtual void on_end_frame();
```

In `source/app/bred/gpu/renderer.h`, add after `read_to_cpu_buffer()`:

```cpp
      virtual void on_end_frame();
      virtual void sample_to_cpu_buffer();
```

- [ ] **Step 2: Register contexts after their current layer exists**

In `gpu::context::start_layer()` in `source/app/bred/gpu/context.cpp`, immediately after `pgpurenderer->start_layer(bFirstLayer);`, add:

```cpp
      auto player = ::gpu::current_layer();

      m_pgpudevice->register_frame_context(this, player);
```

Add the context post-frame forwarder near the commented frame lifecycle methods:

```cpp
   void context::on_end_frame()
   {

      if (m_pgpurenderer)
      {

         m_pgpurenderer->on_end_frame();

      }

   }
```

- [ ] **Step 3: Implement renderer output selection**

Include the policy directly in `source/app/bred/gpu/renderer.cpp`:

```cpp
#include "post_frame_context_registry.h"
```

Add after `renderer::read_to_cpu_buffer()`:

```cpp
   void renderer::on_end_frame()
   {

      auto bCpuBuffer =
         m_pgpucontext && m_pgpucontext->m_eoutput == ::gpu::e_output_cpu_buffer;

      ::gpu::dispatch_cpu_sampling(
         bCpuBuffer,
         [this]()
         {

            sample_to_cpu_buffer();

         });

   }


   void renderer::sample_to_cpu_buffer()
   {

      read_to_cpu_buffer();

   }
```

The default remains compatible with renderers that only implement `read_to_cpu_buffer()`. The four active backends receive explicit overrides in Task 3.

- [ ] **Step 4: Implement locked registration and unlocked dispatch**

Add to `source/app/bred/gpu/device.cpp` before `device::start_frame()`:

```cpp
   void device::register_frame_context(::gpu::context *pcontext, ::gpu::layer *player)
   {

      _synchronous_lock lock(this->synchronization());

      m_postframecontextregistry.register_context(pcontext, player);

   }


   void device::dispatch_post_frame_contexts()
   {

      post_frame_context_registry_t::entry_array entrya;
      ::pointer<::gpu::context> pcontextMain;

      {

         _synchronous_lock lock(this->synchronization());

         entrya = m_postframecontextregistry.take_entries();
         pcontextMain = m_pgpucontextMain;

      }

      post_frame_context_registry_t::dispatch(
         std::move(entrya),
         pcontextMain,
         []()
         {

            return ::pointer<::gpu::layer>(::gpu::current_layer());

         },
         [](const ::pointer<::gpu::layer> &player)
         {

            ::gpu::set_current_layer(player);

         },
         [](const ::pointer<::gpu::context> &pcontext)
         {

            pcontext->on_end_frame();

         });

   }
```

At the beginning of `device::start_frame()`, clear the prior registry under the device synchronization before incrementing the frame serial:

```cpp
      {

         _synchronous_lock lock(this->synchronization());

         m_postframecontextregistry.clear();

      }
```

Change `device::end_frame()` so the new dispatch occurs after existing device and `frame::end_frame()` processing, outside the lock:

```cpp
   void device::end_frame()
   {

      on_end_frame();

      {

         _synchronous_lock lock(this->synchronization());

         auto pframe = current_frame();

         pframe->end_frame();

      }

      dispatch_post_frame_contexts();

   }
```

- [ ] **Step 5: Run the standalone policy and ordering tests**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\gpu\tests\post_frame_context_registry_tests.cpp /Fo:`"$env:TEMP\post_frame_context_registry_tests.obj`" /Fe:`"$env:TEMP\post_frame_context_registry_tests.exe`" && `"$env:TEMP\post_frame_context_registry_tests.exe`""
```

Expected: exit 0, covering deduplication, latest-layer selection, main-last ordering, exception continuation, layer restoration, and CPU sampling selection.

- [ ] **Step 6: Build the common framework**

Run:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild 'source\app\bred\bred.vcxproj' /t:Build /m /p:Configuration=Debug /p:Platform=x64
```

Expected: `Build succeeded` with no errors in the new lifecycle declarations, pointer ownership, or registry dispatch.

- [ ] **Step 7: Commit the common lifecycle**

```powershell
git -C source/app add -- bred/gpu/device.h bred/gpu/device.cpp bred/gpu/context.h bred/gpu/context.cpp bred/gpu/renderer.h bred/gpu/renderer.cpp
git -C source/app commit -m "fix: dispatch GPU context post-frame processing"
```

Expected: one commit containing only the common device/context/renderer lifecycle.

### Task 3: Backend CPU sampling adapters

**Files:**
- Modify: `source/app/gpu_opengl/renderer.h:75`
- Modify: `source/app/gpu_opengl/renderer.cpp:910`
- Modify: `operating_system/operating_system-windows_common/gpu_directx11/renderer.h:143`
- Modify: `operating_system/operating_system-windows_common/gpu_directx11/renderer.cpp:708`
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.h:138`
- Modify: `source/app-graphics3d/gpu_vulkan/renderer.cpp:1376`
- Modify: `source/app-graphics3d/gpu_directx12/renderer.h:202`
- Modify: `source/app-graphics3d/gpu_directx12/renderer.cpp:1517`

**Interfaces:**
- Consumes: `virtual gpu::renderer::sample_to_cpu_buffer()` from Task 2.
- Produces: Four backend overrides forwarding to existing readback implementations.

- [ ] **Step 1: Add the OpenGL adapter**

In `source/app/gpu_opengl/renderer.h`, add beside `do_sampling_to_cpu()`:

```cpp
      void sample_to_cpu_buffer() override;
```

In `source/app/gpu_opengl/renderer.cpp`, immediately before `do_sampling_to_cpu()`, add:

```cpp
   void renderer::sample_to_cpu_buffer()
   {

      do_sampling_to_cpu();

   }
```

- [ ] **Step 2: Add the DirectX 11 adapter**

In `operating_system/operating_system-windows_common/gpu_directx11/renderer.h`, add beside `do_sampling_to_cpu()`:

```cpp
      void sample_to_cpu_buffer() override;
```

In `operating_system/operating_system-windows_common/gpu_directx11/renderer.cpp`, immediately before `do_sampling_to_cpu()`, add:

```cpp
   void renderer::sample_to_cpu_buffer()
   {

      do_sampling_to_cpu();

   }
```

- [ ] **Step 3: Add the Vulkan adapter**

In `source/app-graphics3d/gpu_vulkan/renderer.h`, add beside `sample()`:

```cpp
      void sample_to_cpu_buffer() override;
```

In `source/app-graphics3d/gpu_vulkan/renderer.cpp`, immediately before `sample()`, add:

```cpp
   void renderer::sample_to_cpu_buffer()
   {

      sample();

   }
```

- [ ] **Step 4: Add the DirectX 12 adapter**

In `source/app-graphics3d/gpu_directx12/renderer.h`, add beside `sample()`:

```cpp
      void sample_to_cpu_buffer() override;
```

In `source/app-graphics3d/gpu_directx12/renderer.cpp`, immediately before `sample()`, add:

```cpp
   void renderer::sample_to_cpu_buffer()
   {

      sample();

   }
```

- [ ] **Step 5: Build all backend projects**

Run:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
$projects = @(
   'source\app\gpu_opengl\gpu_opengl.vcxproj',
   'operating_system\operating_system-windows_common\gpu_directx11\gpu_directx11.vcxproj',
   'source\app-graphics3d\gpu_vulkan\gpu_vulkan.vcxproj',
   'source\app-graphics3d\gpu_directx12\gpu_directx12.vcxproj'
)

foreach ($project in $projects)
{

   & $msbuild $project /t:Build /m /p:Configuration=Debug /p:Platform=x64

   if ($LASTEXITCODE -ne 0) { throw "Build failed: $project" }

}
```

Expected: all four builds report `Build succeeded`; no override-signature mismatch or unresolved symbol remains.

- [ ] **Step 6: Commit each repository's backend adapter**

```powershell
git -C source/app add -- gpu_opengl/renderer.h gpu_opengl/renderer.cpp
git -C source/app commit -m "fix: route OpenGL post-frame CPU sampling"

git -C operating_system add -- operating_system-windows_common/gpu_directx11/renderer.h operating_system-windows_common/gpu_directx11/renderer.cpp
git -C operating_system commit -m "fix: route DirectX 11 post-frame CPU sampling"

git -C source/app-graphics3d add -- gpu_vulkan/renderer.h gpu_vulkan/renderer.cpp gpu_directx12/renderer.h gpu_directx12/renderer.cpp
git -C source/app-graphics3d commit -m "fix: route explicit GPU post-frame CPU sampling"
```

Expected: three scoped commits, one in each affected repository.

### Task 4: Integration verification and runtime handoff

**Files:**
- Verify: `source/app/bred/gpu/device.cpp`
- Verify: `source/app/bred/gpu/context.cpp`
- Verify: `source/app/bred/gpu/renderer.cpp`
- Verify: all four backend `renderer.cpp` files from Task 3
- Verify: `source/app-graphics3d/continuum/__implement/shared_app_graphics3d_continuum.vcxproj`

**Interfaces:**
- Consumes: Tested common lifecycle and four backend adapters.
- Produces: A freshly built continuum application ready for offscreen OpenGL behavioral confirmation.

- [ ] **Step 1: Verify repository scope and whitespace**

Run:

```powershell
git status --short
git -C source/app status --short
git -C operating_system status --short
git -C source/app-graphics3d status --short
git -C source/app diff --check HEAD~3..HEAD
git -C operating_system diff --check HEAD~1..HEAD
git -C source/app-graphics3d diff --check HEAD~1..HEAD
```

Expected: no unintended working-tree changes and no whitespace errors. Confirm all modified C++ and project files use CRLF.

- [ ] **Step 2: Run the standalone tests freshly**

Run:

```powershell
$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /d /c "`"$vcvars`" >nul && cl.exe /nologo /std:c++20 /EHsc source\app\bred\gpu\tests\post_frame_context_registry_tests.cpp /Fo:`"$env:TEMP\post_frame_context_registry_tests.obj`" /Fe:`"$env:TEMP\post_frame_context_registry_tests.exe`" && `"$env:TEMP\post_frame_context_registry_tests.exe`""
```

Expected: compilation and execution exit 0.

- [ ] **Step 3: Build the continuum application and dependencies**

Run:

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild 'source\app-graphics3d\continuum\__implement\shared_app_graphics3d_continuum.vcxproj' /t:Build /m /p:Configuration=Debug /p:Platform=x64
```

Expected: `Build succeeded` and the Debug x64 continuum executable is refreshed.

- [ ] **Step 4: Commit the nested source-repository pointers**

After confirming only `app` and `app-graphics3d` moved inside the `source` repository, run:

```powershell
git -C source add -- app app-graphics3d
git -C source commit -m "fix: update GPU post-frame sampling components"
```

Expected: one `source` commit recording only the intended `app` and `app-graphics3d` pointers.

- [ ] **Step 5: Commit the root submodule pointers**

After confirming only the intended nested repositories moved, run:

```powershell
git add -- source operating_system
git commit -m "fix: restore GPU post-frame CPU sampling"
```

Expected: a root commit recording only the intended `source` and `operating_system` pointers.

- [ ] **Step 6: Perform the user-visible OpenGL offscreen check**

Ask the user to run `shared_app_graphics3d_continuum` with OpenGL and offscreen rendering. Confirm all of the following before calling the symptom fixed:

1. the 3D scene appears as the sampled bitmap inside the draw2d_gdiplus window hierarchy;
2. the GUI continues repainting while the offscreen frame loop runs;
3. memory remains stable under the previously implemented `m_fDesiredFps` limiter;
4. switching back to on-screen swap-chain mode still renders the layered 3D scene and GUI without CPU readback.
