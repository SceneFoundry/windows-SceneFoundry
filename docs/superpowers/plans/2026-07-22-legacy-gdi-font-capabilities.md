# Separate Legacy GDI Font Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let draw2d backends independently accept or reject Windows raster fonts and legacy GDI type-zero/other fonts, with NanoVG rejecting both categories before font-list enumeration.

**Architecture:** Preserve the existing `write_text_supports_raster_fonts()` capability and add `write_text_supports_legacy_gdi_fonts()` beside it in Aura. Both default to enabled. NanoVG disables both, and `write_text_win32::font_enumeration` maps them independently to its existing `m_bRaster` and `m_bOther` source filters before `EnumFontFamiliesW` runs.

**Tech Stack:** C++20, ca2 Aura draw2d/write_text interfaces, Windows GDI `EnumFontFamiliesW`, NanoVG, standalone source-contract tests, MSBuild Debug/x64.

## Global Constraints

- Preserve existing line endings when practical and use CRLF for modified C++ files.
- Keep raster and legacy GDI type-zero/other support as separate virtual capabilities.
- Both base capabilities default to `true`; NanoVG overrides both to `false`.
- Do not hardcode `Modern`, `Roman`, `Script`, or any other font-family names in production filtering.
- Do not cast or type-check the active backend as `draw2d_nanovg` from Aura or `write_text_win32`.
- Keep `TRUETYPE_FONTTYPE` enumeration unchanged.
- Preserve unrelated dirty OpenGL and NanoVG diagnostic changes.

---

### Task 1: Aura Legacy-GDI Capability

**Files:**
- Modify: `source/app/aura/graphics/draw2d/draw2d.h`
- Modify: `source/app/aura/graphics/draw2d/draw2d.cpp`
- Modify: `source/app/aura/graphics/write_text/tests/raster_font_capability_contract_test.cpp`

**Interfaces:**
- Existing: `virtual bool ::draw2d::draw2d::write_text_supports_raster_fonts()`
- Produces: `virtual bool ::draw2d::draw2d::write_text_supports_legacy_gdi_fonts()`
- Default result: `true`

- [ ] **Step 1: Extend the Aura contract before production changes**

Add assertions for the new virtual and isolate its implementation from the following graphics-context capability:

```cpp
assert(header.find("virtual bool write_text_supports_legacy_gdi_fonts();") != std::string::npos);

const auto legacyCapability = source.find("bool draw2d::write_text_supports_legacy_gdi_fonts()");
const auto nextMethod = source.find(
   "bool draw2d::graphics_context_supports_single_buffer_mode()",
   legacyCapability);

assert(legacyCapability != std::string::npos);
assert(nextMethod != std::string::npos);

const auto legacyImplementation = source.substr(
   legacyCapability,
   nextMethod - legacyCapability);

assert(legacyImplementation.find("return true;") != std::string::npos);
```

- [ ] **Step 2: Run the contract and verify RED**

Run from `source/app`:

```powershell
g++ aura\graphics\write_text\tests\raster_font_capability_contract_test.cpp -std=c++17 -o $env:TEMP\raster_font_capability_contract_test.exe
& $env:TEMP\raster_font_capability_contract_test.exe
```

Expected: assertion failure because `write_text_supports_legacy_gdi_fonts()` is absent.

- [ ] **Step 3: Add the default Aura capability**

Add beside the raster capability in `draw2d.h`:

```cpp
virtual bool write_text_supports_legacy_gdi_fonts();
```

Add between the raster and graphics-context capability implementations in `draw2d.cpp`:

```cpp
bool draw2d::write_text_supports_legacy_gdi_fonts()
{

   return true;

}
```

- [ ] **Step 4: Verify GREEN and build Aura**

Run the contract again, then run:

```powershell
msbuild source\app\aura\aura.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: contract exit code 0 and MSBuild reports no errors.

- [ ] **Step 5: Commit the Aura capability**

```powershell
git -C source\app add -- aura/graphics/draw2d/draw2d.h aura/graphics/draw2d/draw2d.cpp aura/graphics/write_text/tests/raster_font_capability_contract_test.cpp
git -C source\app commit -m "feat: distinguish legacy GDI font capability"
```

### Task 2: NanoVG Rejects Both Legacy Categories

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/font_context_registration_contract_test.cpp`

**Interfaces:**
- Consumes: `virtual bool ::draw2d::draw2d::write_text_supports_legacy_gdi_fonts()`
- Produces: `bool draw2d_nanovg::draw2d::write_text_supports_legacy_gdi_fonts() override`
- NanoVG result: `false`

- [ ] **Step 1: Extend the NanoVG contract and verify RED**

Add the header assertion and isolate both capability implementations:

```cpp
assert(header.find("write_text_supports_legacy_gdi_fonts() override") != std::string::npos);

const auto rasterCapability = section(
   source,
   "bool draw2d::write_text_supports_raster_fonts()",
   "bool draw2d::write_text_supports_legacy_gdi_fonts()");
const auto legacyCapability = section(
   source,
   "bool draw2d::write_text_supports_legacy_gdi_fonts()",
   "bool draw2d::graphics_context_supports_single_buffer_mode()");

assert(rasterCapability.find("return false;") != std::string::npos);
assert(legacyCapability.find("return false;") != std::string::npos);
```

Compile and run from `source/app-graphics3d`:

```powershell
g++ draw2d_nanovg\tests\font_context_registration_contract_test.cpp -std=c++17 -o $env:TEMP\font_context_registration_contract_test.exe
& $env:TEMP\font_context_registration_contract_test.exe
```

Expected: assertion failure because the legacy-GDI override is absent.

- [ ] **Step 2: Implement the NanoVG override**

Add beside the raster override in `draw2d_nanovg/draw2d.h`:

```cpp
bool write_text_supports_legacy_gdi_fonts() override;
```

Add between the raster and graphics-context capability implementations in `draw2d_nanovg/draw2d.cpp`:

```cpp
bool draw2d::write_text_supports_legacy_gdi_fonts()
{

   return false;

}
```

- [ ] **Step 3: Verify GREEN and build NanoVG**

Run the contract again, then run:

```powershell
msbuild source\app-graphics3d\draw2d_nanovg\draw2d_nanovg.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: contract exit code 0 and MSBuild reports no errors.

- [ ] **Step 4: Commit only the NanoVG capability files**

```powershell
git -C source\app-graphics3d add -- draw2d_nanovg/draw2d.h draw2d_nanovg/draw2d.cpp draw2d_nanovg/tests/font_context_registration_contract_test.cpp
git -C source\app-graphics3d diff --cached --check
git -C source\app-graphics3d commit -m "feat: reject legacy GDI fonts in NanoVG"
```

Do not stage the unrelated modified `draw2d_nanovg/graphics.cpp`, `graphics.h`, or GPU-image diagnostics contract.

### Task 3: Windows Independent Source Filters

**Files:**
- Modify: `operating_system/operating_system-windows/write_text_win32/font_enumeration.cpp`
- Modify: `operating_system/operating_system-windows/write_text_win32/tests/font_enumeration_capability_contract_test.cpp`

**Interfaces:**
- Consumes: `system()->draw2d()->write_text_supports_raster_fonts()`
- Consumes: `system()->draw2d()->write_text_supports_legacy_gdi_fonts()`
- Uses existing flags: `::write_text::font_enumeration::m_bRaster`, `::write_text::font_enumeration::m_bOther`

- [ ] **Step 1: Extend the Windows contract before production changes**

Require independent capability checks and ordering before enumeration:

```cpp
const auto rasterCapability = enumerate.find("write_text_supports_raster_fonts()");
const auto disableRaster = enumerate.find("m_bRaster = false", rasterCapability);
const auto legacyCapability = enumerate.find("write_text_supports_legacy_gdi_fonts()", disableRaster);
const auto disableOther = enumerate.find("m_bOther = false", legacyCapability);
const auto enumFonts = enumerate.find("EnumFontFamiliesW", disableOther);

assert(rasterCapability != std::string::npos);
assert(disableRaster != std::string::npos);
assert(legacyCapability != std::string::npos);
assert(disableOther != std::string::npos);
assert(enumFonts != std::string::npos);
assert(rasterCapability < disableRaster);
assert(disableRaster < legacyCapability);
assert(legacyCapability < disableOther);
assert(disableOther < enumFonts);
```

- [ ] **Step 2: Run the Windows contract and verify RED**

Run from `operating_system`:

```powershell
g++ operating_system-windows\write_text_win32\tests\font_enumeration_capability_contract_test.cpp -std=c++17 -o $env:TEMP\font_enumeration_capability_contract_test.exe
& $env:TEMP\font_enumeration_capability_contract_test.exe
```

Expected: assertion failure because the legacy-GDI capability and `m_bOther` assignment are absent.

- [ ] **Step 3: Apply both capabilities independently**

Keep the existing raster block and add before `EnumFontFamiliesW`:

```cpp
if (!system()->draw2d()->write_text_supports_legacy_gdi_fonts())
{

   m_bOther = false;

}
```

- [ ] **Step 4: Verify GREEN and build write_text_win32**

Run the updated contract and existing resolver contract:

```powershell
g++ operating_system-windows\write_text_win32\tests\font_enumeration_capability_contract_test.cpp -std=c++17 -o $env:TEMP\font_enumeration_capability_contract_test.exe
& $env:TEMP\font_enumeration_capability_contract_test.exe
g++ operating_system-windows\write_text_win32\tests\font_face_resolver_contract_test.cpp -std=c++17 -o $env:TEMP\font_face_resolver_contract_test.exe
& $env:TEMP\font_face_resolver_contract_test.exe
msbuild operating_system\operating_system-windows\write_text_win32\write_text_win32.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: both contracts exit 0 and MSBuild reports no errors.

- [ ] **Step 5: Commit the Windows source filter**

```powershell
git -C operating_system\operating_system-windows add -- write_text_win32/font_enumeration.cpp write_text_win32/tests/font_enumeration_capability_contract_test.cpp
git -C operating_system\operating_system-windows commit -m "fix: filter unsupported legacy GDI fonts"
```

### Task 4: Integrated Verification

**Files:**
- Verify only; no production edits expected.

**Interfaces:**
- Validates the separate raster and legacy-GDI capability flow from Aura through NanoVG into Windows enumeration.

- [ ] **Step 1: Run all font capability contracts**

Run the Aura capability contract, NanoVG font-context contract, Windows enumeration capability contract, and Windows font-face resolver contract. Expected: all four exit with code 0.

- [ ] **Step 2: Rebuild integrated Debug/x64 targets**

Run in dependency order:

```powershell
msbuild source\app\aura\aura.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild operating_system\operating_system-windows\write_text_win32\write_text_win32.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild source\app-graphics3d\draw2d_nanovg\draw2d_nanovg.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild source\app-graphics3d\continuum\__implement\shared_app_graphics3d_continuum.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: all four builds complete without MSBuild errors.

- [ ] **Step 3: Audit repository state**

Run `git diff --check` in the three modified nested repositories. Confirm only the intended capability commits were added and unrelated OpenGL/NanoVG files remain unstaged.

- [ ] **Step 4: Runtime validation handoff**

Run Continuum with NanoVG. Expected: enumeration omits raster fonts such as `Courier` and type-zero legacy GDI fonts such as `Modern`, `Roman`, and `Script`; TrueType/OpenType previews continue to enumerate and render.
