# Pixmap Vertical-Swap Row Address Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reverse pixmap rows in place without shifted rows or out-of-bounds access for non-square and padded-stride images.

**Architecture:** Retain `pixmap_t::vertical_swap()` as the shared CPU row-orientation boundary used by OpenGL pixel transfers. Correct the bottom-row address with byte-stride arithmetic and protect degenerate or invalid layouts before allocating scratch storage.

**Tech Stack:** C++20, SceneFoundry `pixmap_t`, Visual Studio/MSBuild, a focused native regression executable.

## Global Constraints

- Work directly on `main`, as explicitly authorized by the user.
- Preserve unrelated edits in `source/app/gpu_opengl/texture.cpp` and `source/app/gpu_opengl/texture.h`.
- Preserve existing line endings when practical.
- Use Windows CRLF line endings for new and modified C++ source files.
- Do not change WIC decoding, OpenGL texture upload orientation, shaders, MSAA composition or resolve, or the HelloMultiverse IPC layout.

---

### Task 1: Correct Shared Pixmap Vertical Row Swapping

**Files:**
- Create: `source/app/acme/test/graphics/pixmap_vertical_swap.cpp`
- Modify: `source/app/acme/graphics/image/pixmap.cpp:356`

**Interfaces:**
- Consumes: `pixmap_t::initialize_pixmap(const ::i32_size &, ::image32_t *, ::i32)` and `pixmap_t::vertical_swap()`.
- Produces: Correct in-place row reversal for active pixel bytes while preserving row padding and surrounding guard bytes.

- [ ] **Step 1: Write the failing behavioral test**

Create a native test that initializes a 3-by-4 pixmap over four rows with a
16-byte stride: 12 active bytes and 4 padding bytes per row. Put distinct
literal pixel values in every row, distinct padding values after every row,
and guard bytes before and after the pixmap storage.

Call:

```cpp
pixmap.initialize_pixmap({3, 4}, pixelData, 16);
pixmap.vertical_swap();
```

Assert literal expected rows in the order row 3, row 2, row 1, row 0. Assert
that every padding byte and both guard regions retain their original literal
values.

The production mutation this test catches is using any width/height-derived
offset instead of `stride * (height - 1)` for the bottom row.

- [ ] **Step 2: Build and run the focused test to verify RED**

Build the current Debug/x64 `acme` dependency through the provided solution,
compile the focused executable against that library, and run it:

```powershell
& "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe" `
  solution-windows\SceneFoundry.sln `
  /t:acme `
  /p:Configuration=Debug `
  /p:Platform=x64 `
  /m
```

Compile `source/app/acme/test/graphics/pixmap_vertical_swap.cpp` using the
Visual Studio x64 developer environment, the repository include root, and the
Debug/x64 `acme` import library produced by the solution build.

Expected: the executable returns a nonzero exit code because the current
bottom-row address shifts active rows and writes into guard storage.

- [ ] **Step 3: Implement the minimal shared-helper correction**

In `pixmap_t::vertical_swap()`, derive:

```cpp
auto pdata = (::u8 *)ppixmap->image32();
auto iRowBytes = ppixmap->width() * (::i32)sizeof(::image32_t);
auto h = ppixmap->height();
```

Return when `pdata` is null, `iRowBytes <= 0`, `h <= 1`, or
`iStride < iRowBytes`. Then initialize the row pointers with:

```cpp
auto pline1 = pdata;
auto pline2 = pdata + iStride * (h - 1);
```

Keep the existing scratch-row three-copy loop, advancing and retreating by
the byte stride.

- [ ] **Step 4: Preserve C++ line endings**

Normalize the new test and modified `pixmap.cpp` to Windows CRLF without
changing their content.

- [ ] **Step 5: Rebuild and rerun the focused test to verify GREEN**

Rebuild `acme`, rebuild the focused executable, and run it again.

Expected: exit code 0; active rows are reversed and all padding/guard bytes are
unchanged.

- [ ] **Step 6: Build the Continuum application**

Run:

```powershell
& "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe" `
  solution-windows\SceneFoundry.sln `
  /t:app_graphics3d_continuum `
  /p:Configuration=Debug `
  /p:Platform=x64 `
  /m `
  /clp:ErrorsOnly
```

Expected: build succeeds with zero errors.

- [ ] **Step 7: Review the final diff and preserve scope**

Confirm the production change is limited to `pixmap_t::vertical_swap()`, the
behavioral regression, and the approved spec/plan. Confirm the unrelated
`gpu_opengl` edits remain untouched.
