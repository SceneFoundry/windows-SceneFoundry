# Vulkan Cubemap Native Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Vulkan six-image cubemap staging path explicitly apply the native Vulkan face order and per-face rotations without modifying source images.

**Architecture:** Keep Vulkan resource management in `buffer::_assign_cube_map` and isolate the upload convention in the CPU-only `pack_cube_map_for_vulkan` helper. The helper owns a named face-rule table and applies either an unchanged copy or a direct 180-degree pixel copy for each destination layer.

**Tech Stack:** C++20, Vulkan staging buffers, MSBuild/Visual Studio, standalone GNU C++ regression test.

## Global Constraints

- Preserve Windows CRLF line endings for modified C++ and project files.
- Destination source order must be `{0, 1, 3, 2, 5, 4}` for Vulkan layers positive X, negative X, positive Y, negative Y, positive Z, and negative Z.
- Positive X, negative X, positive Z, and negative Z must be rotated 180 degrees.
- Positive Y and negative Y must be copied unchanged.
- Source pointers and source pixels must remain unchanged.
- KTX, HDR, shaders, Vulkan image creation, and other graphics backends remain unchanged.

---

### Task 1: Replace the OpenGL-compatible packer with the explicit Vulkan-native packer

**Files:**
- Modify: `source/app-graphics3d/gpu_vulkan/tests/cube_map_upload_test.cpp`
- Modify: `source/app-graphics3d/gpu_vulkan/cube_map_upload.h`
- Modify: `source/app-graphics3d/gpu_vulkan/buffer.cpp:303`

**Interfaces:**
- Consumes: `PIXEL *pdestination`, shared `width` and `height`, six source pixel pointers, and six source byte strides.
- Produces: `gpu_vulkan::pack_cube_map_for_vulkan<PIXEL>(PIXEL *, int, int, const PIXEL *const[6], const int[6])`.

- [ ] **Step 1: Change the regression test to require the Vulkan-native function and rule table**

Update the function call to `pack_cube_map_for_vulkan`. For each 2x2 destination face, require these exact source values:

```cpp
   constexpr std::array<int, 6> sourceFaceIndices{0, 1, 3, 2, 5, 4};
   constexpr std::array<bool, 6> rotate180{true, true, false, false, true, true};

   for (std::size_t destinationFace = 0;
        destinationFace < sourceFaceIndices.size();
        ++destinationFace)
   {

      const auto &sourceFace = source[sourceFaceIndices[destinationFace]];
      const auto destinationOffset = destinationFace * 4;

      if (rotate180[destinationFace])
      {

         assert(destination[destinationOffset + 0] == sourceFace[3]);
         assert(destination[destinationOffset + 1] == sourceFace[2]);
         assert(destination[destinationOffset + 2] == sourceFace[1]);
         assert(destination[destinationOffset + 3] == sourceFace[0]);

      }
      else
      {

         assert(destination[destinationOffset + 0] == sourceFace[0]);
         assert(destination[destinationOffset + 1] == sourceFace[1]);
         assert(destination[destinationOffset + 2] == sourceFace[2]);
         assert(destination[destinationOffset + 3] == sourceFace[3]);

      }

   }
```

Keep `assert(source == sourceBefore)` to prove the source is not mutated.

- [ ] **Step 2: Run the regression test to verify RED**

Run:

```powershell
g++ -std=c++20 -Wall -Wextra -Werror `
  source/app-graphics3d/gpu_vulkan/tests/cube_map_upload_test.cpp `
  -o "$env:TEMP/cube_map_upload_test.exe"
```

Expected: compilation fails because `pack_cube_map_for_vulkan` is not defined. This proves the updated test does not pass against the current OpenGL-compatible helper.

- [ ] **Step 3: Implement the named Vulkan rule table and packer**

Replace `pack_cube_map_like_opengl` in `cube_map_upload.h` with:

```cpp
   enum class enum_cube_map_copy_operation
   {

      copy_unchanged,
      rotate_180,

   };


   struct cube_map_face_rule
   {

      int m_iSourceFace;
      enum_cube_map_copy_operation m_eoperation;

   };


   template < typename PIXEL >
   void pack_cube_map_for_vulkan(
      PIXEL *pdestination,
      int width,
      int height,
      const PIXEL *const psourcefaces[6],
      const int sourcescana[6])
   {

      constexpr cube_map_face_rule vulkanCubeMapFaceRules[6] =
      {

         {0, enum_cube_map_copy_operation::rotate_180},    // Positive X
         {1, enum_cube_map_copy_operation::rotate_180},    // Negative X
         {3, enum_cube_map_copy_operation::copy_unchanged},// Positive Y
         {2, enum_cube_map_copy_operation::copy_unchanged},// Negative Y
         {5, enum_cube_map_copy_operation::rotate_180},    // Positive Z
         {4, enum_cube_map_copy_operation::rotate_180},    // Negative Z

      };

      const auto destinationScan = static_cast<std::size_t>(width) * sizeof(PIXEL);
      const auto destinationFaceSize = destinationScan * static_cast<std::size_t>(height);
      auto *pdestinationBytes = reinterpret_cast<std::byte *>(pdestination);

      for (int destinationFace = 0; destinationFace < 6; ++destinationFace)
      {

         const auto &rule = vulkanCubeMapFaceRules[destinationFace];
         const auto *psourceBytes =
            reinterpret_cast<const std::byte *>(psourcefaces[rule.m_iSourceFace]);
         auto *pdestinationFace =
            pdestinationBytes + destinationFaceSize * destinationFace;

         for (int y = 0; y < height; ++y)
         {

            const auto sourceY =
               rule.m_eoperation == enum_cube_map_copy_operation::rotate_180
                  ? height - y - 1
                  : y;
            const auto *psourceRow = reinterpret_cast<const PIXEL *>(
               psourceBytes + static_cast<std::size_t>(sourceY) * sourcescana[rule.m_iSourceFace]);
            auto *pdestinationRow = reinterpret_cast<PIXEL *>(
               pdestinationFace + static_cast<std::size_t>(y) * destinationScan);

            if (rule.m_eoperation == enum_cube_map_copy_operation::rotate_180)
            {

               for (int x = 0; x < width; ++x)
               {

                  pdestinationRow[x] = psourceRow[width - x - 1];

               }

            }
            else
            {

               std::memcpy(pdestinationRow, psourceRow, destinationScan);

            }

         }

      }

   }
```

- [ ] **Step 4: Rename the staging call**

In `buffer::_assign_cube_map`, replace the existing helper call with:

```cpp
      pack_cube_map_for_vulkan(
         static_cast < image32_t * >(data), w, h, psourcefaces, sourcescana);
```

- [ ] **Step 5: Run the regression test to verify GREEN**

Run:

```powershell
g++ -std=c++20 -Wall -Wextra -Werror `
  source/app-graphics3d/gpu_vulkan/tests/cube_map_upload_test.cpp `
  -o "$env:TEMP/cube_map_upload_test.exe"
& "$env:TEMP/cube_map_upload_test.exe"
```

Expected: compilation and execution both exit with code 0.

- [ ] **Step 6: Run source checks**

Run:

```powershell
git -C source/app-graphics3d diff --check
rg -n "pack_cube_map_like_opengl|rotate\(180_degrees\)|swap\(imagea" `
  source/app-graphics3d/gpu_vulkan/buffer.cpp `
  source/app-graphics3d/gpu_vulkan/cube_map_upload.h
```

Expected: `diff --check` exits 0 and `rg` finds none of the obsolete helper or high-level source-image mutation calls.

- [ ] **Step 7: Build the affected Visual Studio target**

Run:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' `
  solution-windows/SceneFoundry.sln `
  /t:shared_app_graphics3d_continuum `
  /p:Configuration=Debug `
  /p:Platform=x64 `
  /m `/nologo `/v:minimal
```

Expected: exit code 0, with `gpu_vulkan.vcxproj` producing `gpu_vulkan.dll` and `shared_app_graphics3d_continuum.vcxproj` producing the executable.

- [ ] **Step 8: Commit the implementation after runtime visual verification**

Stage only the focused Vulkan files and the finalized plan after the user confirms the scene orientation:

```powershell
git -C source/app-graphics3d add -- `
  gpu_vulkan/cube_map_upload.h `
  gpu_vulkan/tests/cube_map_upload_test.cpp `
  gpu_vulkan/buffer.cpp `
  gpu_vulkan/gpu_vulkan.vcxproj `
  gpu_vulkan/gpu_vulkan.vcxproj.filters
git -C source/app-graphics3d commit -m "fix: apply native Vulkan cubemap orientation"
```

Final runtime verification: run `shared_app_graphics3d_continuum` with Vulkan and compare all six named faces against OpenGL.
