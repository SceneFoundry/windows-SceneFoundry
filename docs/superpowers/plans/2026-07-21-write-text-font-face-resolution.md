# Windows Font Face Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Windows logical font families, styles, substitutions, and TTC face indexes through `write_text_win32`, then load the resolved face independently in every NanoVG context.

**Architecture:** Aura owns platform-neutral `font_face_request` and `font_face_source` value types plus a virtual resolver on `write_text::write_text`. `write_text_win32` follows Windows FontSubstitutes and queries DirectWrite for a local file and collection index, caching successful descriptors under the existing font synchronization. `draw2d_nanovg` consumes only the neutral interface and registers a style-specific NanoVG font with `nvgCreateFontAtIndex()`.

**Tech Stack:** C++20, Aura `write_text`, Win32 registry APIs, DirectWrite (`dwrite.lib`), NanoVG/FontStash, Visual Studio/MSBuild, standalone C++ contract tests.

## Global Constraints

- Preserve existing user changes; never reset or overwrite the dirty worktrees.
- Use CRLF for all new and modified C++ and project files.
- Stage only files and hunks belonging to the current task; `source/app-graphics3d/draw2d_nanovg/graphics.cpp` and related files already contain other diagnostics.
- Keep DirectWrite and Windows registry types out of Aura and `draw2d_nanovg` headers.
- Keep font registration per `NVGcontext`; do not restore a global `loaded` flag.
- Do not use an unconditional Arial fallback. Arial is valid for `Arabic Transparent` only through the Windows FontSubstitutes entry.
- Cache only successful resolutions and clear the cache when system font enumeration refreshes.
- Support one local OpenType/TrueType backing file per resolved face; report nonlocal and multi-file faces explicitly.
- Existing path-only platform behavior remains available through the Aura base implementation with face index zero.

---

### Task 1: Add the platform-neutral Aura font-face contract

**Files:**
- Create: `source/app/aura/graphics/write_text/font_face.h`
- Create: `source/app/aura/graphics/write_text/tests/font_face_resolution_contract_test.cpp`
- Modify: `source/app/aura/graphics/write_text/write_text.h:1-65`
- Modify: `source/app/aura/graphics/write_text/write_text.cpp:120-155`
- Modify: `source/app/aura/aura.vcxproj:2890-3270`
- Modify: `source/app/aura/aura.vcxproj.filters:1270-1340`
- Modify: `source/app/aura/CMakeLists.txt:220-265`

**Interfaces:**
- Consumes: `write_text::font_weight`, `file::path`, and the existing `platform::node::get_font_path_from_name()` compatibility lookup.
- Produces: `write_text::font_face_request`, `write_text::font_face_source`, and `virtual bool write_text::write_text::resolve_font_face(font_face_source &, const font_face_request &)`.

- [ ] **Step 1: Write the failing Aura source contract**

Create `font_face_resolution_contract_test.cpp` as a standalone source contract. It must read `font_face.h`, `write_text.h`, and `write_text.cpp`, then assert these exact responsibilities:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>

static std::string read_file(const char * path)
{
   std::ifstream stream(path, std::ios::binary);
   return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

int main()
{
   const auto face = read_file("aura/graphics/write_text/font_face.h");
   const auto header = read_file("aura/graphics/write_text/write_text.h");
   const auto source = read_file("aura/graphics/write_text/write_text.cpp");

   assert(face.find("struct CLASS_DECL_AURA font_face_request") != std::string::npos);
   assert(face.find("m_strFamily") != std::string::npos);
   assert(face.find("m_fontweight") != std::string::npos);
   assert(face.find("m_bItalic") != std::string::npos);
   assert(face.find("struct CLASS_DECL_AURA font_face_source") != std::string::npos);
   assert(face.find("m_path") != std::string::npos);
   assert(face.find("m_iFaceIndex") != std::string::npos);
   assert(face.find("m_strResolvedFamily") != std::string::npos);
   assert(header.find("virtual bool resolve_font_face(") != std::string::npos);
   assert(source.find("write_text::resolve_font_face(") != std::string::npos);
   assert(source.find("get_font_path_from_name") != std::string::npos);
   assert(source.find("m_iFaceIndex = 0") != std::string::npos);
   return 0;
}
```

- [ ] **Step 2: Run the Aura contract and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$devcmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
cmd.exe /d /s /c ('"' + $devcmd + '" -arch=x64 -host_arch=x64 >nul && cl /nologo /EHsc /std:c++20 aura\graphics\write_text\tests\font_face_resolution_contract_test.cpp /Fe:' + $env:TEMP + '\font_face_resolution_contract_test.exe && ' + $env:TEMP + '\font_face_resolution_contract_test.exe')
```

Expected: FAIL because `font_face.h` and the virtual resolver do not exist.

- [ ] **Step 3: Add the neutral value types**

Create `font_face.h` with only platform-neutral types:

```cpp
#pragma once

#include "acme/filesystem/filesystem/path.h"
#include "acme/graphics/write_text/font_weight.h"

namespace write_text
{

   struct CLASS_DECL_AURA font_face_request
   {
      ::string m_strFamily;
      font_weight m_fontweight = e_font_weight_normal;
      bool m_bItalic = false;
   };

   struct CLASS_DECL_AURA font_face_source
   {
      ::file::path m_path;
      int m_iFaceIndex = 0;
      ::string m_strResolvedFamily;
   };

} // namespace write_text
```

Include it from `write_text.h` and declare:

```cpp
virtual bool resolve_font_face(
   ::write_text::font_face_source & source,
   const ::write_text::font_face_request & request);
```

- [ ] **Step 4: Implement the compatibility resolver**

In `write_text.cpp`, clear all output fields before resolving and succeed only for a real path:

```cpp
bool write_text::resolve_font_face(
   ::write_text::font_face_source & source,
   const ::write_text::font_face_request & request)
{
   source = {};
   source.m_strResolvedFamily = request.m_strFamily;
   source.m_path = node()->get_font_path_from_name(request.m_strFamily);
   source.m_iFaceIndex = 0;

   return source.m_path.has_character() && file()->exists(source.m_path);
}
```

Add `font_face.h` to the Aura MSBuild and CMake header lists and place it under the existing write-text header filter.

- [ ] **Step 5: Verify GREEN and build Aura**

Run the contract command from Step 2. Expected: PASS.

Then run from the repository root:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$env:CL = '/I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include\configuration_selection\Debug" /I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include" /I"C:\Users\camilo\SceneFoundry\main\port\common\debugbreak"'
& $msbuild source\app\aura\aura.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir='C:\Users\camilo\SceneFoundry\main\solution-windows\' /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `aura.vcxproj` builds without errors.

- [ ] **Step 6: Commit the Aura contract**

```powershell
git -C source\app add -- aura\graphics\write_text\font_face.h aura\graphics\write_text\write_text.h aura\graphics\write_text\write_text.cpp aura\graphics\write_text\tests\font_face_resolution_contract_test.cpp aura\aura.vcxproj aura\aura.vcxproj.filters aura\CMakeLists.txt
git -C source\app diff --cached --check
git -C source\app commit -m "feat: add font face resolution contract"
```

Expected: only the listed Aura files are committed; the existing `gpu_opengl` changes remain unstaged.

---

### Task 2: Implement the DirectWrite font-face resolver

**Files:**
- Create: `operating_system/operating_system-windows/write_text_win32/font_face_resolver.h`
- Create: `operating_system/operating_system-windows/write_text_win32/font_face_resolver.cpp`
- Create: `operating_system/operating_system-windows/write_text_win32/tests/font_face_resolver_contract_test.cpp`
- Modify: `operating_system/operating_system-windows/write_text_win32/write_text_win32.vcxproj:970-2600`
- Modify: `operating_system/operating_system-windows/write_text_win32/write_text_win32.vcxproj.filters:1-50`
- Modify: `operating_system/operating_system-windows/write_text_win32/CMakeLists.txt:5-40`

**Interfaces:**
- Consumes: `write_text::font_face_request` and `write_text::font_face_source` from Task 1.
- Produces: `write_text_win32::font_face_resolver::resolve()`, `resolve_substitute_family()`, and `clear()` with no Aura service or NanoVG dependency.

- [ ] **Step 1: Write the failing Windows resolver contract**

Create a standalone contract that reads the new resolver source and build manifests:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>

static std::string read_file(const char * path)
{
   std::ifstream stream(path, std::ios::binary);
   return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

int main()
{
const auto header = read_file("operating_system-windows/write_text_win32/font_face_resolver.h");
const auto source = read_file("operating_system-windows/write_text_win32/font_face_resolver.cpp");
const auto project = read_file("operating_system-windows/write_text_win32/write_text_win32.vcxproj");
const auto cmake = read_file("operating_system-windows/write_text_win32/CMakeLists.txt");

assert(header.find("class CLASS_DECL_WRITE_TEXT_WIN32 font_face_resolver") != std::string::npos);
assert(header.find("resolve_substitute_family") != std::string::npos);
assert(header.find("bool resolve(") != std::string::npos);
assert(source.find("FontSubstitutes") != std::string::npos);
assert(source.find("DWriteCreateFactory") != std::string::npos);
assert(source.find("FindFamilyName") != std::string::npos);
assert(source.find("GetFirstMatchingFont") != std::string::npos);
assert(source.find("IDWriteLocalFontFileLoader") != std::string::npos);
assert(source.find("GetFilePathFromKey") != std::string::npos);
assert(source.find("GetIndex()") != std::string::npos);
assert(source.find("FindFamilyName(L\"Arial\"") == std::string::npos);
assert(project.find("Dwrite.lib") != std::string::npos);
assert(cmake.find("Dwrite") != std::string::npos);
return 0;
}
```

- [ ] **Step 2: Run the resolver contract and verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\operating_system`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$devcmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
cmd.exe /d /s /c ('"' + $devcmd + '" -arch=x64 -host_arch=x64 >nul && cl /nologo /EHsc /std:c++20 operating_system-windows\write_text_win32\tests\font_face_resolver_contract_test.cpp /Fe:' + $env:TEMP + '\font_face_resolver_contract_test.exe && ' + $env:TEMP + '\font_face_resolver_contract_test.exe')
```

Expected: FAIL because the resolver files and DirectWrite link dependency do not exist.

- [ ] **Step 3: Add the resolver class and substitution behavior**

Declare a focused class in `font_face_resolver.h`:

```cpp
namespace write_text_win32
{

   class CLASS_DECL_WRITE_TEXT_WIN32 font_face_resolver :
      virtual public ::particle
   {
   public:
      ::comptr<IDWriteFactory> m_pdwritefactory;
      ::comptr<IDWriteFontCollection> m_pfontcollection;

      ::string resolve_substitute_family(const ::scoped_string & family);
      bool resolve(
         ::write_text::font_face_source & source,
         const ::write_text::font_face_request & request);
      void clear();
   };

} // namespace write_text_win32
```

`resolve_substitute_family()` must query `HKCU` before `HKLM`, treat registry names case-insensitively, strip a trailing numeric charset after the last comma, and follow no more than 16 substitutions. Maintain a case-insensitive visited-name array; on a cycle or depth overflow, log `[write_text_win32.font_face] substitution_cycle` and return the last nonrepeated family.

- [ ] **Step 4: Implement DirectWrite face and local-file resolution**

Implement one resolution path with these exact API decisions:

```cpp
source = {};
source.m_strResolvedFamily = resolve_substitute_family(request.m_strFamily);

::wstring wstrFamily(source.m_strResolvedFamily);
::u32 familyIndex = 0;
BOOL exists = FALSE;
::comptr<IDWriteFontFamily> pfontfamily;
::comptr<IDWriteFont> pfont;
::comptr<IDWriteFontFace> pfontface;

DWriteCreateFactory(
   DWRITE_FACTORY_TYPE_SHARED,
   __uuidof(IDWriteFactory),
   reinterpret_cast<IUnknown **>(&m_pdwritefactory));

m_pdwritefactory->GetSystemFontCollection(&m_pfontcollection);
m_pfontcollection->FindFamilyName(wstrFamily, &familyIndex, &exists);
m_pfontcollection->GetFontFamily(familyIndex, &pfontfamily);
pfontfamily->GetFirstMatchingFont(
   static_cast<DWRITE_FONT_WEIGHT>(request.m_fontweight.as_i32()),
   DWRITE_FONT_STRETCH_NORMAL,
   request.m_bItalic ? DWRITE_FONT_STYLE_ITALIC : DWRITE_FONT_STYLE_NORMAL,
   &pfont);
pfont->CreateFontFace(&pfontface);
source.m_iFaceIndex = static_cast<int>(pfontface->GetIndex());
```

Extract the single local backing file with this API sequence, checking every `HRESULT` before advancing:

```cpp
::u32 fileCount = 0;
pfontface->GetFiles(&fileCount, nullptr);
if (fileCount != 1)
   return false;

::comptr<IDWriteFontFile> pfontfile;
pfontface->GetFiles(&fileCount, &pfontfile);

const void * pReferenceKey = nullptr;
::u32 referenceKeySize = 0;
pfontfile->GetReferenceKey(&pReferenceKey, &referenceKeySize);

::comptr<IDWriteFontFileLoader> pfontfileloader;
pfontfile->GetLoader(&pfontfileloader);

::comptr<IDWriteLocalFontFileLoader> plocalfontfileloader;
pfontfileloader->QueryInterface(
   __uuidof(IDWriteLocalFontFileLoader),
   reinterpret_cast<void **>(&plocalfontfileloader));

::u32 pathLength = 0;
plocalfontfileloader->GetFilePathLengthFromKey(
   pReferenceKey, referenceKeySize, &pathLength);

::wstring wstrPath;
auto pwszPath = wstrPath.get_buffer(pathLength + 1);
plocalfontfileloader->GetFilePathFromKey(
   pReferenceKey, referenceKeySize, pwszPath, pathLength + 1);
wstrPath.release_buffer();

source.m_path = wstrPath;
return GetFileAttributesW(wstrPath) != INVALID_FILE_ATTRIBUTES;
```

At every failure boundary, log one stable category under `[write_text_win32.font_face]`: `factory_failed`, `collection_failed`, `family_not_found`, `face_not_found`, `multiple_files`, `nonlocal_file`, `path_failed`, or `path_missing`. Do not substitute an arbitrary family inside this class.

- [ ] **Step 5: Register source files and DirectWrite build dependencies**

Add the new header/source to `write_text_win32.vcxproj`, its filters file, and `CMakeLists.txt`. Mechanically change all twelve MSBuild link entries from:

```xml
<AdditionalDependencies>Gdiplus.lib;%(AdditionalDependencies)</AdditionalDependencies>
```

to:

```xml
<AdditionalDependencies>Gdiplus.lib;Dwrite.lib;%(AdditionalDependencies)</AdditionalDependencies>
```

Add `Dwrite` to the MSVC CMake `target_link_libraries()` entry.

- [ ] **Step 6: Verify GREEN and build `write_text_win32`**

Run the resolver contract. Expected: PASS.

Build:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$env:CL = '/I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include\configuration_selection\Debug" /I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include" /I"C:\Users\camilo\SceneFoundry\main\port\common\debugbreak"'
& $msbuild operating_system\operating_system-windows\write_text_win32\write_text_win32.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir='C:\Users\camilo\SceneFoundry\main\solution-windows\' /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `write_text_win32.dll` links successfully with `Dwrite.lib`.

- [ ] **Step 7: Commit the resolver**

```powershell
git -C operating_system add -- operating_system-windows\write_text_win32\font_face_resolver.h operating_system-windows\write_text_win32\font_face_resolver.cpp operating_system-windows\write_text_win32\tests\font_face_resolver_contract_test.cpp operating_system-windows\write_text_win32\write_text_win32.vcxproj operating_system-windows\write_text_win32\write_text_win32.vcxproj.filters operating_system-windows\write_text_win32\CMakeLists.txt
git -C operating_system diff --cached --check
git -C operating_system commit -m "feat: resolve Windows font face files with DirectWrite"
```

---

### Task 3: Connect resolver caching to the `write_text_win32` provider

**Files:**
- Modify: `operating_system/operating_system-windows/write_text_win32/write_text.h:1-35`
- Modify: `operating_system/operating_system-windows/write_text_win32/write_text.cpp:1-30`
- Modify: `operating_system/operating_system-windows/write_text_win32/tests/font_face_resolver_contract_test.cpp`

**Interfaces:**
- Consumes: `font_face_resolver` from Task 2 and Aura's virtual `resolve_font_face()` from Task 1.
- Produces: the active Windows `write_text` provider override, successful-resolution cache, and cache invalidation on font enumeration refresh.

- [ ] **Step 1: Extend the contract and verify RED**

Add assertions requiring the Win32 provider to contain:

```cpp
assert(writeTextHeader.find("resolve_font_face(") != std::string::npos);
assert(writeTextHeader.find("handle_font_enumeration(") != std::string::npos);
assert(writeTextHeader.find("m_mapFontFaceSource") != std::string::npos);
assert(writeTextSource.find("resolve_substitute_family") != std::string::npos);
assert(writeTextSource.find("::write_text::write_text::resolve_font_face") != std::string::npos);
assert(writeTextSource.find("m_mapFontFaceSource.clear()") != std::string::npos);
```

Run the resolver contract. Expected: FAIL because the provider does not override or cache resolution.

- [ ] **Step 2: Add provider state and overrides**

Add to `write_text_win32::write_text`:

```cpp
::pointer<font_face_resolver> m_pfontfaceresolver;
string_map_base<::write_text::font_face_source> m_mapFontFaceSource;

bool resolve_font_face(
   ::write_text::font_face_source & source,
   const ::write_text::font_face_request & request) override;
void handle_font_enumeration(::topic * ptopic) override;
void destroy() override;
```

Construct the resolver lazily while holding `m_csFont`. Build a deterministic cache key from the case-folded requested family, `request.m_fontweight.as_i32()`, and `request.m_bItalic`. Return cached successes immediately and never store a failure.

- [ ] **Step 3: Implement resolution fallback and invalidation**

The override uses the existing map API and releases the font lock before invoking the base resolver:

```cpp
bool write_text::resolve_font_face(
   ::write_text::font_face_source & source,
   const ::write_text::font_face_request & request)
{
   auto strFamilyKey = request.m_strFamily;
   strFamilyKey.make_lower();

   ::string strKey;
   strKey.formatf(
      "%s|%d|%d",
      strFamilyKey.c_str(),
      request.m_fontweight.as_i32(),
      request.m_bItalic ? 1 : 0);

critical_section_lock lock(&m_csFont);

   if (auto ppair = m_mapFontFaceSource.plookup(strKey))
   {
      source = ppair->element2();
      return true;
   }

   if (!m_pfontfaceresolver)
   {
      construct_newø(m_pfontfaceresolver);
   }

   if (m_pfontfaceresolver->resolve(source, request))
   {
      m_mapFontFaceSource[strKey] = source;
      return true;
   }

   auto requestFallback = request;
   requestFallback.m_strFamily =
      m_pfontfaceresolver->resolve_substitute_family(request.m_strFamily);
   lock.unlock();

   return ::write_text::write_text::resolve_font_face(source, requestFallback);
}
```

For the compatibility call, copy the request and replace only `m_strFamily` with the substitute-resolved family. Preserve weight and italic. `handle_font_enumeration()` clears the descriptor map and calls `font_face_resolver::clear()` under the lock, releases the lock, then calls `::write_text::write_text::handle_font_enumeration(ptopic)`. `destroy()` releases the resolver and cache before delegating to the base class.

- [ ] **Step 4: Verify GREEN, build, and commit**

Run the resolver contract command from `C:\Users\camilo\SceneFoundry\main\operating_system`. Expected: PASS.

Then build the provider:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$env:CL = '/I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include\configuration_selection\Debug" /I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include" /I"C:\Users\camilo\SceneFoundry\main\port\common\debugbreak"'
& $msbuild operating_system\operating_system-windows\write_text_win32\write_text_win32.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir='C:\Users\camilo\SceneFoundry\main\solution-windows\' /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `write_text_win32.dll` links successfully.

```powershell
git -C operating_system add -- operating_system-windows\write_text_win32\write_text.h operating_system-windows\write_text_win32\write_text.cpp operating_system-windows\write_text_win32\tests\font_face_resolver_contract_test.cpp
git -C operating_system diff --cached --check
git -C operating_system commit -m "feat: expose cached Windows font face resolution"
```

---

### Task 4: Load style-specific resolved faces in each NanoVG context

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.h:35-65`
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.cpp:249-295`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h` at the font-loading declaration
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:7999-8035,10118-10123`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/font_context_registration_contract_test.cpp`

**Interfaces:**
- Consumes: the active `write_text::write_text::resolve_font_face()` virtual interface.
- Produces: `draw2d_nanovg::draw2d::defer_load_font(NVGcontext *, write_text::font *) -> string`, returning the exact context-local NanoVG registration key selected by `graphics::_set()`.

- [ ] **Step 1: Update the existing NanoVG contract and verify RED**

Replace the family-only assertions with assertions requiring:

```cpp
assert(loadFont.find("resolve_font_face") != std::string::npos);
assert(loadFont.find("nvgCreateFontAtIndex") != std::string::npos);
assert(loadFont.find("m_iFaceIndex") != std::string::npos);
assert(loadFont.find("m_fontweight.as_i32()") != std::string::npos);
assert(loadFont.find("m_bItalic") != std::string::npos);
assert(loadFont.find("get_font_path_from_name") == std::string::npos);
assert(loadFont.find("nvgCreateFont(") == std::string::npos);
assert(header.find("m_mapFont") == std::string::npos);
assert(header.find("m_bLoaded") == std::string::npos);
```

Also inspect `graphics::_set()` and require it to pass the returned registration key to `nvgFontFace()` rather than the family name.

Run from `source/app-graphics3d`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$devcmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
cmd.exe /d /s /c ('"' + $devcmd + '" -arch=x64 -host_arch=x64 >nul && cl /nologo /EHsc /std:c++20 draw2d_nanovg\tests\font_context_registration_contract_test.cpp /Fe:' + $env:TEMP + '\font_context_registration_contract_test.exe && ' + $env:TEMP + '\font_context_registration_contract_test.exe')
```

Expected: FAIL because the current code uses `nvgCreateFont()` and a family-only key.

- [ ] **Step 2: Change the NanoVG font-loading interface**

Replace `defer_load_font_by_family_name()` with:

```cpp
virtual ::string defer_load_font(
   NVGcontext * pdc,
   ::write_text::font * pfont);
```

The implementation builds a request from `pfont->family_name()`, `pfont->m_fontweight`, and `pfont->m_bItalic`. Construct a stable context key containing all three logical properties, for example:

```cpp
strFontKey.formatf(
   "family=%s;weight=%d;italic=%d",
   request.m_strFamily.c_str(),
   request.m_fontweight.as_i32(),
   request.m_bItalic ? 1 : 0);
```

- [ ] **Step 3: Resolve and register the face per context**

While holding the existing recursive NanoVG mutex:

```cpp
auto iFont = nvgFindFont(pdc, strFontKey);
if (iFont >= 0)
   return strFontKey;

::write_text::font_face_source source;
auto pwritetext = system()->draw2d()->write_text();
if (!pwritetext->resolve_font_face(source, request))
{
   ::string strMessage;
   strMessage.formatf(
      "NanoVG font face resolution failed. requested_family=\"%s\" "
      "weight=%d italic=%d resolved_family=\"%s\" path=\"%s\" "
      "face_index=%d exists=false.",
      request.m_strFamily.c_str(),
      request.m_fontweight.as_i32(),
      request.m_bItalic ? 1 : 0,
      source.m_strResolvedFamily.c_str(),
      source.m_path.c_str(),
      source.m_iFaceIndex);
   information() << "[draw2d_nanovg.font] " << strMessage;
   throw ::exception(error_failed, strMessage);
}

iFont = nvgCreateFontAtIndex(
   pdc,
   strFontKey,
   source.m_path,
   source.m_iFaceIndex);
if (iFont < 0)
{
   const auto bExists =
      source.m_path.has_character() && file()->exists(source.m_path);
   ::string strMessage;
   strMessage.formatf(
      "NanoVG rejected a resolved font face. requested_family=\"%s\" "
      "weight=%d italic=%d resolved_family=\"%s\" path=\"%s\" "
      "face_index=%d exists=%s.",
      request.m_strFamily.c_str(),
      request.m_fontweight.as_i32(),
      request.m_bItalic ? 1 : 0,
      source.m_strResolvedFamily.c_str(),
      source.m_path.c_str(),
      source.m_iFaceIndex,
      bExists ? "true" : "false");
   information() << "[draw2d_nanovg.font] " << strMessage;
   throw ::exception(error_failed, strMessage);
}

return strFontKey;
```

Both failure messages must contain requested family, weight, italic, resolved family, path, face index, and file existence. Preserve the `[draw2d_nanovg.font]` log prefix.

- [ ] **Step 4: Select the returned key in `graphics::_set()`**

Change the graphics helper to accept `write_text::font *` and return the string from the draw2d service. `_set()` must use:

```cpp
const auto strFontKey = defer_load_font(pfontParam);
nvgFontFace(m_pdc, strFontKey);
```

Do not use the family name in `nvgFontFace()` after this point.

- [ ] **Step 5: Verify NanoVG contracts and build**

Run these standalone contracts from `source/app-graphics3d`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$devcmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
$tests = @(
   'font_context_registration_contract_test',
   'gpu_image_boundary_diagnostics_contract_test',
   'gpu_image_fast_path_test',
   'gpu_image_lifecycle_test',
   'graphics_lease_integration_contract_test',
   'memory_graphics_lifecycle_test')
foreach ($test in $tests)
{
   $command = '"' + $devcmd + '" -arch=x64 -host_arch=x64 >nul && cl /nologo /EHsc /std:c++20 draw2d_nanovg\tests\' + $test + '.cpp /Fe:' + $env:TEMP + '\' + $test + '.exe && ' + $env:TEMP + '\' + $test + '.exe'
   cmd.exe /d /s /c $command
   if ($LASTEXITCODE -ne 0) { throw "$test failed" }
}
```

Expected: every contract exits with code zero.

Build `draw2d_nanovg.vcxproj`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$env:CL = '/I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include\configuration_selection\Debug" /I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include" /I"C:\Users\camilo\SceneFoundry\main\port\common\debugbreak"'
& $msbuild source\app-graphics3d\draw2d_nanovg\draw2d_nanovg.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir='C:\Users\camilo\SceneFoundry\main\solution-windows\' /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `draw2d_nanovg.dll` links successfully.

- [ ] **Step 6: Commit only the font-loading hunks**

Because these files already contain other work, inspect every hunk and stage only the font resolution changes:

```powershell
git -C source\app-graphics3d diff -- draw2d_nanovg\draw2d.h draw2d_nanovg\draw2d.cpp draw2d_nanovg\graphics.h draw2d_nanovg\graphics.cpp draw2d_nanovg\tests\font_context_registration_contract_test.cpp
git -C source\app-graphics3d add -p -- draw2d_nanovg\draw2d.h draw2d_nanovg\draw2d.cpp draw2d_nanovg\graphics.h draw2d_nanovg\graphics.cpp
git -C source\app-graphics3d add -- draw2d_nanovg\tests\font_context_registration_contract_test.cpp
git -C source\app-graphics3d diff --cached --check
git -C source\app-graphics3d commit -m "fix: load resolved font faces in NanoVG contexts"
```

Expected: GPU image diagnostics unrelated to font loading remain unstaged.

---

### Task 5: Perform integrated build and runtime validation

**Files:**
- Verify only; no new production files.

**Interfaces:**
- Consumes: all outputs of Tasks 1-4.
- Produces: build evidence and runtime evidence that logical substitutes, collection indexes, per-context registration, transparency, and scrolling work together.

- [ ] **Step 1: Run repository hygiene checks**

Run `git diff --check` and `git status --short` separately in `source/app`, `operating_system`, and `source/app-graphics3d`. Expected: no whitespace errors and no accidentally staged unrelated files.

- [ ] **Step 2: Rebuild the dependency chain**

Build Debug x64 in dependency order:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$env:CL = '/I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include\configuration_selection\Debug" /I"C:\Users\camilo\SceneFoundry\main\operating_system\operating_system-windows\include" /I"C:\Users\camilo\SceneFoundry\main\port\common\debugbreak"'
$projects = @(
   'source\app\aura\aura.vcxproj',
   'operating_system\operating_system-windows\write_text_win32\write_text_win32.vcxproj',
   'source\app-graphics3d\draw2d_nanovg\draw2d_nanovg.vcxproj',
   'source\app-graphics3d\continuum\__implement\shared_app_graphics3d_continuum.vcxproj')
foreach ($project in $projects)
{
   & $msbuild $project /t:Build /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /p:SolutionDir='C:\Users\camilo\SceneFoundry\main\solution-windows\' /m:1 /nodeReuse:false /nologo /v:minimal
   if ($LASTEXITCODE -ne 0) { throw "$project failed" }
}
```

Expected: every project reports build success.

- [ ] **Step 3: Validate the deployed DLL mirror**

Compare SHA-256 hashes of the C: and H: Debug copies of `aura.dll`, `write_text_win32.dll`, and `draw2d_nanovg.dll`. Expected: each C:/H: pair matches before Visual Studio starts the application.

- [ ] **Step 4: Run the application under validation layers and diagnostics**

Start the continuum application with OpenGL and `draw2d_nanovg`. Exercise font enumeration and scroll the font list. Expected:

- no exception for `Arabic Transparent`;
- a diagnostic resolution showing its resolved family is `Arial` through FontSubstitutes;
- font previews contain visible glyphs over transparent backgrounds instead of black rectangles;
- `.ttc` families render without `nvgCreateFontAtIndex()` failure;
- regular, bold, and italic faces do not alias;
- repeated pooled graphics contexts register fonts independently;
- scrolling remains responsive and GPU-image diagnostics do not show new CPU mapping.

- [ ] **Step 5: Record any unsupported Windows font source without masking it**

If a nonlocal or multi-file face is encountered, capture the `[write_text_win32.font_face]` category and requested family. Do not add a generic fallback. Treat that evidence as a separate design decision because NanoVG FontStash accepts one local file and one face index.
