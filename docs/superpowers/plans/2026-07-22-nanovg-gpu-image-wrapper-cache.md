# NanoVG GPU Image Wrapper Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep imported OpenGL texture wrappers valid through NanoVG's deferred flush, reuse them across frames, and bound their GPU-texture retention.

**Architecture:** Each `draw2d_nanovg::graphics` owns a cache whose entries are valid only for that graphics object's `NVGcontext`. `_draw_gpu_image` acquires or creates a wrapper keyed by texture serial, OpenGL object, and dimensions; `on_end_layer` evicts stale or least-recently-used entries only after `nvgEndFrame`; every `NVGcontext` destruction path clears the cache.

**Tech Stack:** C++20, NanoVG GL3, OpenGL, SceneFoundry `gpu::texture`, source-contract executables, Visual Studio/MSBuild Debug x64.

## Global Constraints

- Preserve the GPU-only draw path; do not map, unmap, upload, or CPU-sample the source image.
- Cache ownership is per `draw2d_nanovg::graphics`/`NVGcontext`; do not add a global cache.
- Use `(texture serial, OpenGL texture identifier, width, height)` as the cache key.
- Hold a strong `::pointer<::gpu::texture>` in every live cache entry.
- Never delete a wrapper before the `nvgEndFrame` that may consume it.
- Evict entries after 120 unused completed graphics frames and prefer at most 512 entries per graphics instance.
- Never evict an entry used in the frame that just completed; allow temporary overflow when one frame uses more than 512 textures.
- Perform NanoVG cache operations on the owning graphics GPU-context thread under the existing NanoVG synchronization.
- Preserve CRLF line endings in modified C++ source and test files.
- Do not modify or stage unrelated worktree changes.

---

### Task 1: Add the persistent per-context wrapper cache

**Files:**
- Create: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h:9-73,135-167`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:8780-8942`

**Interfaces:**
- Consumes: `::gpu::texture::m_iTextureSerial`
- Consumes: `::gpu_opengl::texture::m_gluTextureID`
- Produces: `int graphics::acquire_nanovg_gpu_image_wrapper(::gpu_opengl::texture *, const ::i32_size &, bool &)`
- Produces: `nanovg_gpu_image_wrapper_cache_entry`, privately owned in effect by one `graphics` instance
- Changes: `record_gpu_image_fast_path(bool, bool, ::u64, ::u64)` receives whether acquisition created a wrapper

- [ ] **Step 1: Write the failing cache contract**

Create `gpu_image_wrapper_cache_contract_test.cpp` with:

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

   const auto header = read_file("draw2d_nanovg/graphics.h");
   const auto source = read_file("draw2d_nanovg/graphics.cpp");

   assert(header.find("struct nanovg_gpu_image_wrapper_cache_entry") !=
      std::string::npos);
   assert(header.find("m_iTextureSerial") != std::string::npos);
   assert(header.find("m_uOpenGlTexture") != std::string::npos);
   assert(header.find("m_size") != std::string::npos);
   assert(header.find("m_iNanovgImage") != std::string::npos);
   assert(header.find("::pointer < ::gpu::texture > m_pgputexture") !=
      std::string::npos);
   assert(header.find("m_uLastUsedFrame") != std::string::npos);
   assert(header.find("m_nanovgGpuImageWrapperCache") != std::string::npos);
   assert(header.find("acquire_nanovg_gpu_image_wrapper(") !=
      std::string::npos);

   const auto acquire = section(
      source,
      "int graphics::acquire_nanovg_gpu_image_wrapper(",
      "bool graphics::_draw_gpu_image(");
   assert(acquire.find("m_iTextureSerial == pgputexture->m_iTextureSerial") !=
      std::string::npos);
   assert(acquire.find("m_uOpenGlTexture == pgputexture->m_gluTextureID") !=
      std::string::npos);
   assert(acquire.find("m_size.cx == sizeImage.cx") != std::string::npos);
   assert(acquire.find("m_size.cy == sizeImage.cy") != std::string::npos);
   assert(acquire.find("nvglCreateImageFromHandleGL3(") !=
      std::string::npos);
   assert(acquire.find("NVG_IMAGE_NODELETE") != std::string::npos);
   assert(acquire.find("entry.m_pgputexture = pgputexture;") !=
      std::string::npos);
   assert(acquire.find("m_nanovgGpuImageWrapperCache.push_back(") !=
      std::string::npos);

   const auto gpuPath = section(
      source,
      "bool graphics::_draw_gpu_image(",
      "void graphics::_draw_raw(");
   assert(gpuPath.find("acquire_nanovg_gpu_image_wrapper(") !=
      std::string::npos);
   assert(gpuPath.find("nvgDeleteImage(") == std::string::npos);
   assert(gpuPath.find("->map(") == std::string::npos);
   assert(gpuPath.find("read_pixels(") == std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Compile and run the new contract to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app-graphics3d`:

```powershell
g++ draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
```

Expected: the executable aborts because the cache entry and acquisition interface do not exist.

- [ ] **Step 3: Declare the cache entry, state, and helper interfaces**

Add `#include <vector>` after the existing standard-library includes in `graphics.h`, then add the following inside `graphics`, before the performance counters:

```cpp
      struct nanovg_gpu_image_wrapper_cache_entry
      {

         ::collection::index                 m_iTextureSerial = -1;
         ::u32                               m_uOpenGlTexture = 0;
         ::i32_size                          m_size;
         int                                 m_iNanovgImage = 0;
         ::pointer < ::gpu::texture >        m_pgputexture;
         ::u64                               m_uLastUsedFrame = 0;

      };

      ::std::vector < nanovg_gpu_image_wrapper_cache_entry >
         m_nanovgGpuImageWrapperCache;
      ::u64 m_uNanovgGpuImageWrapperFrameSerial = 0;
```

Add these declarations beside `_draw_gpu_image`:

```cpp
      int acquire_nanovg_gpu_image_wrapper(
         ::gpu_opengl::texture * pgputexture,
         const ::i32_size & sizeImage,
         bool & bCreatedWrapper);
      void maintain_nanovg_gpu_image_wrapper_cache();
      void clear_nanovg_gpu_image_wrapper_cache();
```

Change the diagnostic recorder declaration to:

```cpp
      void record_gpu_image_fast_path(
         bool bWaitedForFence,
         bool bCreatedWrapper,
         ::u64 uFenceMicroseconds,
         ::u64 uWrapperMicroseconds);
```

- [ ] **Step 4: Implement cache lookup and wrapper creation**

Insert this method immediately before `_draw_gpu_image` in `graphics.cpp`:

```cpp
   int graphics::acquire_nanovg_gpu_image_wrapper(
      ::gpu_opengl::texture * pgputexture,
      const ::i32_size & sizeImage,
      bool & bCreatedWrapper)
   {

      for (auto & entry : m_nanovgGpuImageWrapperCache)
      {

         if (entry.m_iTextureSerial == pgputexture->m_iTextureSerial
            && entry.m_uOpenGlTexture == pgputexture->m_gluTextureID
            && entry.m_size.cx == sizeImage.cx
            && entry.m_size.cy == sizeImage.cy)
         {

            entry.m_uLastUsedFrame = m_uNanovgGpuImageWrapperFrameSerial;
            bCreatedWrapper = false;

            return entry.m_iNanovgImage;

         }

      }

      auto iImage = nvglCreateImageFromHandleGL3(
         m_pdc,
         pgputexture->m_gluTextureID,
         sizeImage.cx,
         sizeImage.cy,
         NVG_IMAGE_NODELETE |
            NVG_IMAGE_PREMULTIPLIED |
            NVG_IMAGE_FLIPY);

      if (iImage == 0)
      {

         throw ::exception(
            error_failed,
            "NanoVG failed to wrap the OpenGL GPU image texture.");

      }

      nanovg_gpu_image_wrapper_cache_entry entry;
      entry.m_iTextureSerial = pgputexture->m_iTextureSerial;
      entry.m_uOpenGlTexture = pgputexture->m_gluTextureID;
      entry.m_size = sizeImage;
      entry.m_iNanovgImage = iImage;
      entry.m_pgputexture = pgputexture;
      entry.m_uLastUsedFrame = m_uNanovgGpuImageWrapperFrameSerial;
      m_nanovgGpuImageWrapperCache.push_back(entry);
      bCreatedWrapper = true;

      return iImage;

   }
```

Task 2 supplies the declared maintenance and clear methods before the affected library is built.

- [ ] **Step 5: Replace per-draw creation/deletion with cache acquisition**

Inside `_draw_gpu_image`, retain the fence wait, sampled-image diagnostic, NanoVG mutex, size calculation, and wrapper timer. Replace the direct `nvglCreateImageFromHandleGL3` through `nvgDeleteImage` region with:

```cpp
      auto bCreatedWrapper = false;
      auto iImage = acquire_nanovg_gpu_image_wrapper(
         pgputexture,
         sizeImage,
         bCreatedWrapper);
      auto uWrapperMicroseconds = (::u64)0;

      if (bPerformanceDiagnostics)
      {

         uWrapperMicroseconds = (::u64)::std::chrono::duration_cast<
            ::std::chrono::microseconds>(
               ::std::chrono::steady_clock::now() - timeWrapperStart).count();

      }

      _draw_nanovg_image(
         iImage,
         sizeImage,
         rectangleTarget,
         imagedrawingoptions,
         pointSrc);

      if (bPerformanceDiagnostics)
      {

         record_gpu_image_fast_path(
            bPendingFence,
            bCreatedWrapper,
            uFenceMicroseconds,
            uWrapperMicroseconds);

      }
```

Do not leave any `nvgDeleteImage` call inside `_draw_gpu_image`.

- [ ] **Step 6: Make creation accounting conditional**

Change the `record_gpu_image_fast_path` definition signature to include `bool bCreatedWrapper`, then replace the unconditional creation/deletion increments with:

```cpp
      m_uPerformanceGpuImageDraws.fetch_add(1, ::std::memory_order_relaxed);

      if (bCreatedWrapper)
      {

         m_uPerformanceWrapperCreations.fetch_add(
            1,
            ::std::memory_order_relaxed);

      }

      m_uPerformanceWrapperMicroseconds.fetch_add(
         uWrapperMicroseconds,
         ::std::memory_order_relaxed);
```

Keep fence-wait accounting and periodic reporting unchanged. Wrapper deletion accounting moves to post-frame eviction in Task 2.

- [ ] **Step 7: Preserve CRLF and run the focused contract to verify GREEN**

Run from the repository root:

```powershell
$files = @(
  'source/app-graphics3d/draw2d_nanovg/graphics.h',
  'source/app-graphics3d/draw2d_nanovg/graphics.cpp',
  'source/app-graphics3d/draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp')
foreach ($file in $files) {
  $path = Resolve-Path $file
  $text = [System.IO.File]::ReadAllText($path)
  $text = $text -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
Set-Location source/app-graphics3d
g++ draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract failed' }
```

Expected: the focused contract exits with code `0`.

- [ ] **Step 8: Commit the persistent cache core**

```powershell
git -C source/app-graphics3d add -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "fix: retain NanoVG GPU image wrappers through flush"
```

Expected: one focused core-lifecycle commit; unrelated changes remain unstaged.

---

### Task 2: Add safe post-flush eviction, context cleanup, and cache diagnostics

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp:73-95`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h:55-85,141-155`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:327-348,516-525,5887-5923,8643-8777,9521-9577`

**Interfaces:**
- Consumes: Task 1's `m_nanovgGpuImageWrapperCache` and frame serial
- Produces: `void graphics::maintain_nanovg_gpu_image_wrapper_cache()`
- Produces: `void graphics::clear_nanovg_gpu_image_wrapper_cache()`
- Produces diagnostics: `wrapper_cache_hits`, `wrapper_cache_misses`, `wrapper_evictions`, and `wrapper_cached`

- [ ] **Step 1: Extend the contract for flush ordering, bounds, and cleanup**

Add these assertions before `return 0` in `gpu_image_wrapper_cache_contract_test.cpp`:

```cpp
   assert(header.find("s_uNanovgGpuImageWrapperStaleFrames = 120") !=
      std::string::npos);
   assert(header.find("s_zNanovgGpuImageWrapperPreferredMaximum = 512") !=
      std::string::npos);
   assert(header.find("m_uPerformanceWrapperCacheHits") !=
      std::string::npos);
   assert(header.find("m_uPerformanceWrapperCacheMisses") !=
      std::string::npos);
   assert(header.find("m_uPerformanceWrapperEvictions") !=
      std::string::npos);

   const auto maintain = section(
      source,
      "void graphics::maintain_nanovg_gpu_image_wrapper_cache()",
      "void graphics::clear_nanovg_gpu_image_wrapper_cache()");
   assert(maintain.find("m_uLastUsedFrame != m_uNanovgGpuImageWrapperFrameSerial") !=
      std::string::npos);
   assert(maintain.find("s_uNanovgGpuImageWrapperStaleFrames") !=
      std::string::npos);
   assert(maintain.find("s_zNanovgGpuImageWrapperPreferredMaximum") !=
      std::string::npos);
   assert(maintain.find("nvgDeleteImage(m_pdc, entry.m_iNanovgImage);") !=
      std::string::npos);

   const auto onEndLayer = section(
      source,
      "void graphics::on_end_layer(",
      "void graphics::start_layer(");
   const auto endFrame = onEndLayer.find("nvgEndFrame(m_pdc);");
   const auto maintainAfterFlush = onEndLayer.find(
      "maintain_nanovg_gpu_image_wrapper_cache();", endFrame);
   const auto advanceFrame = onEndLayer.find(
      "++m_uNanovgGpuImageWrapperFrameSerial;", maintainAfterFlush);
   assert(endFrame != std::string::npos);
   assert(maintainAfterFlush != std::string::npos);
   assert(advanceFrame != std::string::npos);
   assert(endFrame < maintainAfterFlush);
   assert(maintainAfterFlush < advanceFrame);

   const auto windowCreation = section(
      source,
      "void graphics::create_for_window_draw2d(",
      "void graphics::create_compatible_graphics(");
   const auto deleteWindowContext = windowCreation.find("nvgDeleteGL3(m_pdc);");
   const auto clearWindowCache = windowCreation.find(
      "clear_nanovg_gpu_image_wrapper_cache();", deleteWindowContext);
   assert(deleteWindowContext != std::string::npos);
   assert(clearWindowCache != std::string::npos);

   const auto deleteDc = section(
      source,
      "void graphics::DeleteDC()",
      "int graphics::save_graphics_context()");
   assert(deleteDc.find("clear_nanovg_gpu_image_wrapper_cache();") !=
      std::string::npos);

   assert(source.find("wrapper_cache_hits=") != std::string::npos);
   assert(source.find("wrapper_cache_misses=") != std::string::npos);
   assert(source.find("wrapper_evictions=") != std::string::npos);
   assert(source.find("wrapper_cached=") != std::string::npos);
```

In `gpu_image_fast_path_test.cpp`, replace the direct wrapper lifecycle assertions with:

```cpp
   assert(gpuPath.find("acquire_nanovg_gpu_image_wrapper(") !=
      std::string::npos);
   assert(gpuPath.find("NVG_IMAGE_NODELETE") == std::string::npos);
   assert(gpuPath.find("nvgDeleteImage(m_pdc, iImage);") ==
      std::string::npos);
```

Keep the new dedicated contract responsible for verifying `NVG_IMAGE_NODELETE` inside the acquisition helper. The fast-path contract now verifies only that `_draw_gpu_image` dispatches through the cache and does not delete the deferred wrapper.

- [ ] **Step 2: Run the extended contract to verify RED**

Run from `source/app-graphics3d`:

```powershell
g++ draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp -std=c++17 -o "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'contract compilation failed' }
& "$env:TEMP/gpu_image_wrapper_cache_contract_test.exe"
```

Expected: the executable aborts on the first missing bounds or maintenance assertion.

- [ ] **Step 3: Declare bounds and diagnostic counters**

Add these members with the cache state in `graphics.h`:

```cpp
      static constexpr ::u64 s_uNanovgGpuImageWrapperStaleFrames = 120;
      static constexpr ::std::size_t
         s_zNanovgGpuImageWrapperPreferredMaximum = 512;
      ::std::atomic<::u64> m_uPerformanceWrapperCacheHits{0};
      ::std::atomic<::u64> m_uPerformanceWrapperCacheMisses{0};
      ::std::atomic<::u64> m_uPerformanceWrapperEvictions{0};
```

- [ ] **Step 4: Implement stale and capacity eviction**

Insert this method immediately after acquisition:

```cpp
   void graphics::maintain_nanovg_gpu_image_wrapper_cache()
   {

      auto deleteEntry = [this](nanovg_gpu_image_wrapper_cache_entry & entry)
      {

         nvgDeleteImage(m_pdc, entry.m_iNanovgImage);
         m_uPerformanceWrapperDeletions.fetch_add(
            1,
            ::std::memory_order_relaxed);
         m_uPerformanceWrapperEvictions.fetch_add(
            1,
            ::std::memory_order_relaxed);

      };

      for (auto iterator = m_nanovgGpuImageWrapperCache.begin();
           iterator != m_nanovgGpuImageWrapperCache.end();)
      {

         auto & entry = *iterator;
         auto bUsedThisFrame =
            entry.m_uLastUsedFrame == m_uNanovgGpuImageWrapperFrameSerial;
         auto uUnusedFrames = m_uNanovgGpuImageWrapperFrameSerial
            >= entry.m_uLastUsedFrame
            ? m_uNanovgGpuImageWrapperFrameSerial - entry.m_uLastUsedFrame
            : 0;

         if (!bUsedThisFrame
            && uUnusedFrames >= s_uNanovgGpuImageWrapperStaleFrames)
         {

            deleteEntry(entry);
            iterator = m_nanovgGpuImageWrapperCache.erase(iterator);

         }
         else
         {

            ++iterator;

         }

      }

      while (m_nanovgGpuImageWrapperCache.size()
         > s_zNanovgGpuImageWrapperPreferredMaximum)
      {

         auto iteratorOldest = m_nanovgGpuImageWrapperCache.end();

         for (auto iterator = m_nanovgGpuImageWrapperCache.begin();
              iterator != m_nanovgGpuImageWrapperCache.end();
              ++iterator)
         {

            if (iterator->m_uLastUsedFrame
               == m_uNanovgGpuImageWrapperFrameSerial)
            {

               continue;

            }

            if (iteratorOldest == m_nanovgGpuImageWrapperCache.end()
               || iterator->m_uLastUsedFrame
                  < iteratorOldest->m_uLastUsedFrame)
            {

               iteratorOldest = iterator;

            }

         }

         if (iteratorOldest == m_nanovgGpuImageWrapperCache.end())
         {

            break;

         }

         deleteEntry(*iteratorOldest);
         m_nanovgGpuImageWrapperCache.erase(iteratorOldest);

      }

   }
```

- [ ] **Step 5: Implement context cache reset**

Insert this method after maintenance:

```cpp
   void graphics::clear_nanovg_gpu_image_wrapper_cache()
   {

      m_nanovgGpuImageWrapperCache.clear();
      m_uNanovgGpuImageWrapperFrameSerial = 0;

   }
```

This method releases strong texture references but does not call `nvgDeleteImage`; it is used when `nvgDeleteGL3` has already destroyed the owning NanoVG records.

- [ ] **Step 6: Run maintenance strictly after the deferred flush**

Immediately after `nvgEndFrame(m_pdc);` in `on_end_layer`, add:

```cpp
      {

         _synchronous_lock synchronouslock(::draw2d_nanovg::mutex());
         maintain_nanovg_gpu_image_wrapper_cache();

      }

      ++m_uNanovgGpuImageWrapperFrameSerial;
```

Keep render-pixel diagnostics, fence creation, `glFlush`, and the OpenGL error check after this block.

- [ ] **Step 7: Clear cache state on every NanoVG context lifetime boundary**

In the `create_for_window_draw2d` replacement path, change the old-context block to:

```cpp
      if (m_pdc)
      {

         nvgDeleteGL3(m_pdc);
         m_pdc = nullptr;
         clear_nanovg_gpu_image_wrapper_cache();

      }
```

Immediately before creating a memory-graphics `NVGcontext` when `!m_pdc`, call:

```cpp
            clear_nanovg_gpu_image_wrapper_cache();
            m_pdc = nvgCreateGL3(
               NVG_ANTIALIAS | NVG_STENCIL_STROKES | NVG_DEBUG);
```

In `DeleteDC`, call this after the `try`/`catch` that invokes `nvgDeleteGL3(pdc)` and before leaving the `if (m_pdc)` block:

```cpp
         clear_nanovg_gpu_image_wrapper_cache();
```

- [ ] **Step 8: Record cache hits, misses, and evictions**

In `record_gpu_image_fast_path`, replace the `bCreatedWrapper` accounting from Task 1 with:

```cpp
      if (bCreatedWrapper)
      {

         m_uPerformanceWrapperCreations.fetch_add(
            1,
            ::std::memory_order_relaxed);
         m_uPerformanceWrapperCacheMisses.fetch_add(
            1,
            ::std::memory_order_relaxed);

      }
      else
      {

         m_uPerformanceWrapperCacheHits.fetch_add(
            1,
            ::std::memory_order_relaxed);

      }
```

In `reset_gpu_image_performance_diagnostics`, reset the three new counters with relaxed stores, matching the existing counters:

```cpp
      m_uPerformanceWrapperCacheHits.store(0, ::std::memory_order_relaxed);
      m_uPerformanceWrapperCacheMisses.store(0, ::std::memory_order_relaxed);
      m_uPerformanceWrapperEvictions.store(0, ::std::memory_order_relaxed);
```

In `report_gpu_image_performance_diagnostics_if_due`, exchange the interval counters:

```cpp
      auto uWrapperCacheHits = m_uPerformanceWrapperCacheHits.exchange(
         0,
         ::std::memory_order_relaxed);
      auto uWrapperCacheMisses = m_uPerformanceWrapperCacheMisses.exchange(
         0,
         ::std::memory_order_relaxed);
      auto uWrapperEvictions = m_uPerformanceWrapperEvictions.exchange(
         0,
         ::std::memory_order_relaxed);
```

Extend the existing information line before `pending_fence_waits` with:

```cpp
         << " wrapper_cache_hits=" << uWrapperCacheHits
         << " wrapper_cache_misses=" << uWrapperCacheMisses
         << " wrapper_evictions=" << uWrapperEvictions
         << " wrapper_cached=" << m_nanovgGpuImageWrapperCache.size()
```

- [ ] **Step 9: Preserve CRLF and inspect the complete focused diff**

Run from the repository root:

```powershell
$files = @(
  'source/app-graphics3d/draw2d_nanovg/graphics.h',
  'source/app-graphics3d/draw2d_nanovg/graphics.cpp',
  'source/app-graphics3d/draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp')
foreach ($file in $files) {
  $path = Resolve-Path $file
  $text = [System.IO.File]::ReadAllText($path)
  $text = $text -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($path, $text, [System.Text.UTF8Encoding]::new($false))
}
git -C source/app-graphics3d diff --check -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp
git -C source/app-graphics3d diff -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp
```

Expected: no whitespace errors, early wrapper deletion, CPU-map path changes, or unrelated files.

- [ ] **Step 10: Run all focused and neighboring contracts**

Run from `source/app-graphics3d`:

```powershell
$tests = @(
  'gpu_image_wrapper_cache_contract_test',
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

Expected: all six executables exit with code `0`. The existing fast-path contract must be updated in the implementation to require acquisition and forbid `nvgDeleteImage` inside `_draw_gpu_image`, matching the new lifecycle.

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

- [ ] **Step 12: Commit the complete cache implementation**

```powershell
git -C source/app-graphics3d add -- draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_wrapper_cache_contract_test.cpp draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "fix: retain and reuse NanoVG GPU image wrappers"
```

Expected: one focused `source/app-graphics3d` implementation commit; unrelated changes remain unstaged.

---

### Task 3: Validate font previews and steady-state cache behavior

**Files:**
- Inspect only: Visual Studio Output from `shared_app_graphics3d_continuum.exe`

**Interfaces:**
- Consumes: `graphics3d::engine::set_gpu_performance_diagnostics(bool)`
- Produces: runtime evidence for preview correctness, cache reuse, and bounded retention

- [ ] **Step 1: Run the reproducing configuration**

Run Debug x64 `shared_app_graphics3d_continuum` in Visual Studio with OpenGL, swap-chain/on-screen rendering, and `draw2d_nanovg`.

Expected: font enumeration completes and the font list opens.

- [ ] **Step 2: Rearm diagnostics before uncached previews**

Call through the public engine setting immediately before scrolling to unseen font rows:

```cpp
pengine->set_gpu_performance_diagnostics(false);
pengine->set_gpu_performance_diagnostics(true);
```

Expected: the diagnostics generation changes and interval counters restart.

- [ ] **Step 3: Exercise lazy normal and hover previews**

Scroll through several pages of previously unseen fonts, hover multiple font names to create enlarged previews, then revisit those same pages and hover targets.

Expected:

- normal and enlarged previews show text rather than black rectangles;
- no first-use text appears at window position `(0,0)`;
- revisiting previews is responsive;
- `wrapper_cache_hits` grows on revisits;
- `wrapper_cache_misses` tracks only newly encountered textures;
- `wrapper_cached` remains bounded in steady state and does not grow without limit;
- wrapper creation/deletion rates are substantially lower than the previous per-draw rates.

- [ ] **Step 4: Exercise stale eviction**

Continue rendering for at least 120 completed graphics frames after leaving a set of previews unused, while drawing other previews.

Expected: `wrapper_evictions` increases, cached count returns toward the 512 preferred maximum when necessary, and active previews remain correct.

- [ ] **Step 5: Close the application normally**

Close the window after the cache has both hits and evictions.

Expected: no OpenGL validation exception, no invalid NanoVG image access, and no crash while the `NVGcontext` and strong texture references are released.
