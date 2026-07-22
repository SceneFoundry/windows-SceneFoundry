# Windows Font Face Resolution Design

## Problem

`write_text_win32::font_enumeration` uses `EnumFontFamiliesW`, which reports logical Windows font families, including font substitutes. `draw2d_nanovg` later converts each family name to a file using `platform::node::get_font_path_from_name()`. That resolver performs only a few exact lookups in the Windows Fonts registry and returns a path without a font-collection face index.

This breaks for several valid Windows cases:

- `Arabic Transparent` is a Windows font substitute for `Arial`, so it has no direct Fonts registry entry.
- Families such as Cambria and Meiryo are stored in `.ttc` collections and require the correct face index.
- Variable fonts and named family variants do not necessarily have registry value names that equal their enumerated family names.
- Weight and italic selection cannot be represented by a path-only lookup.

The observed failure is an empty path for `Arabic Transparent`, followed by `nvgCreateFont()` returning `-1`. A local comparison also found that the exact registry resolver matched only 88 of 172 installed family names.

## Boundary

Font-face resolution belongs to the active `write_text` implementation, not to `acme::node` and not to a rendering backend.

Aura defines platform-neutral request and result types and a virtual resolution interface. `write_text_win32` implements Windows font semantics using FontSubstitutes and DirectWrite. `draw2d_nanovg` consumes the neutral result and remains independent of DirectWrite, the registry, and Windows-specific types.

The current Windows package selects `write_text_win32` through the existing `write_text` factory. Alternate `write_text` implementations may override the same Aura interface later; NanoVG neither links to nor casts to `write_text_win32`.

The existing node path lookup remains available for compatibility and as the base implementation's path-only fallback. It is not extended with DirectWrite dependencies.

## Aura Interface

Aura's `write_text` layer will define two plain value types:

```cpp
struct font_face_request
{
   string m_strFamily;
   font_weight m_fontweight;
   bool m_bItalic;
};

struct font_face_source
{
   file::path m_path;
   int m_iFaceIndex;
   string m_strResolvedFamily;
};
```

`write_text::write_text` will expose:

```cpp
virtual bool resolve_font_face(
   font_face_source & source,
   const font_face_request & request);
```

The base implementation clears the result, uses the existing platform path lookup, assigns face index zero, and succeeds only when it obtains a nonempty existing path. This preserves a usable default for platforms whose font files are not collections.

The result contains no platform handles. Its lifetime is independent of DirectWrite objects, so callers may cache or pass it across the existing graphics and GPU context boundaries.

## Windows Resolution

`write_text_win32::write_text` overrides `resolve_font_face()` and owns the Windows-specific resolver state.

Resolution proceeds as follows:

1. Normalize the requested family and follow `HKLM` or `HKCU` `FontSubstitutes` entries. Remove an optional charset suffix such as `,178` from the substitute target. Stop on a repeated name or after a fixed maximum depth to prevent substitution cycles.
2. Locate the resulting family in the DirectWrite system font collection.
   If GDI enumeration supplied a face name that is not a DirectWrite family name,
   use `IDWriteGdiInterop::CreateFontFromLOGFONT()` to obtain the corresponding
   DirectWrite font without guessing or truncating style suffixes.
3. Select the closest face with the requested weight, normal stretch, and normal or italic style.
4. Create the DirectWrite font face and obtain its face index.
5. Obtain the face's font file. For a local font file, use `IDWriteLocalFontFileLoader` to obtain the absolute path.
6. Return the path, DirectWrite face index, and resolved family name as `font_face_source`.

Only a single local OpenType/TrueType file is supported by this first implementation because NanoVG FontStash accepts one file and one face index. A nonlocal font or a face requiring multiple files fails explicitly rather than silently selecting an unrelated font.

The implementation caches successful plain descriptors by normalized family, weight, and italic state. It does not negatively cache failures. The cache is cleared when the Windows font enumeration is refreshed so installing or removing a font does not leave stale paths. The existing `write_text` font synchronization protects initialization and cache access because font previews may resolve faces concurrently from pooled graphics-context threads. DirectWrite COM pointers remain inside `write_text_win32` and are released with that service.

If DirectWrite cannot resolve a family, the override invokes the base path-only implementation after substitution. This retains support for an otherwise valid legacy path mapping without replacing a requested family by an arbitrary default.

## Legacy GDI Font Capabilities

Windows GDI enumeration can also report legacy bitmap fonts such as `Courier`,
which is backed by `COURE.FON`. NanoVG accepts only file-backed outline fonts
that FontStash can parse, so a raster font cannot be repaired by name
resolution or passed to `nvgCreateFontAtIndex()`.

GDI also reports the legacy logical/vector families `Modern`, `Roman`, and
`Script` with font type zero. They enter the enumerator's existing `m_bOther`
branch rather than its `m_bRaster` branch. They likewise do not resolve to a
NanoVG-loadable outline face. Raster and type-zero fonts are distinct Windows
font categories and must remain independently representable.

Aura's `draw2d::draw2d` interface exposes two capabilities:

- `write_text_supports_raster_fonts()` controls bitmap/raster enumeration;
- `write_text_supports_legacy_gdi_fonts()` controls the legacy GDI
  type-zero/other enumeration branch.

Both capabilities default to `true`, preserving current behavior for
GDI-capable backends. `draw2d_nanovg::draw2d` overrides both and returns
`false` because neither category can be registered with FontStash.

Before Windows starts `EnumFontFamiliesW`, its font enumerator will read this
pair of capabilities from the active draw2d implementation. It disables
`m_bRaster` when raster fonts are unsupported and independently disables
`m_bOther` when legacy GDI fonts are unsupported. The existing callback then
filters both categories at their source. `TRUETYPE_FONTTYPE` handling remains
unchanged.

The filters are capability-based rather than a NanoVG type check, hardcoded
font-name substitutions, or exception handling in the font list. Other
backends can opt out of either category independently by overriding the
corresponding interface.

## NanoVG Integration

`draw2d_nanovg::graphics::_set()` will build a `font_face_request` from the selected `write_text::font`, including its family, weight, and italic flag. It asks the active `system()->draw2d()->write_text()` service for a `font_face_source`.

NanoVG registration names must distinguish faces. The registration key will include the logical family, weight, and italic state so regular, bold, and italic faces cannot alias one another in a NanoVG context.

The current-context behavior remains:

1. Call `nvgFindFont()` with the face-specific registration key.
2. If absent, call `nvgCreateFontAtIndex()` with the resolved path and face index.
3. Select the same registration key with `nvgFontFace()`.

No global `loaded` flag is introduced. Every NanoVG context registers the font independently, while the platform resolution result may be shared through the `write_text_win32` cache.

## Error Handling and Diagnostics

Resolution failure remains explicit. The NanoVG exception will report the requested family, weight, italic state, resolved family, path, face index, and file existence state.

The resolver will distinguish at least these failure categories in diagnostic output:

- substitution cycle or excessive substitution depth;
- family absent from DirectWrite and the compatibility resolver;
- no matching face;
- nonlocal font file;
- multiple backing files unsupported by NanoVG;
- empty or nonexistent local path;
- `nvgCreateFontAtIndex()` rejecting the resolved face.

There is no unconditional Arial fallback. Arial is used for `Arabic Transparent` only because Windows explicitly declares that substitution.

## Testing

Testing follows red-green-refactor and covers each boundary:

1. An Aura contract verifies that the neutral request/result types and virtual resolver are available without Windows or NanoVG types.
2. A `write_text_win32` resolver test verifies that `Arabic Transparent` follows the Windows substitution and resolves to an existing Arial font file.
3. A collection-font test resolves a known `.ttc` family and verifies that its path and face index can be loaded by NanoVG/FontStash. The test will not hard-code an index when Windows font versions may reorder a collection.
4. A style test verifies that regular, bold, and italic requests produce separately cacheable face descriptors and registration keys.
5. The existing per-NanoVG-context registration contract is extended to require `nvgCreateFontAtIndex()` and face-specific keys.
6. Existing graphics lease, GPU image, OpenGL target-selection, and NanoVG image-boundary contracts continue to pass.
7. Debug x64 builds cover Aura, `write_text_win32`, `draw2d_nanovg`, and the continuum application.
8. Capability contracts verify both Aura defaults, both NanoVG overrides, and
   the Windows enumerator's independent use of each capability before calling
   `EnumFontFamiliesW`.

Runtime validation requires font enumeration to complete without font-loading
exceptions, omit legacy raster-only faces such as `Courier` under NanoVG,
omit legacy GDI type-zero faces such as `Modern`, retain each category for
backends that declare support, render collection-backed faces correctly, and
preserve responsive scrolling.

## Scope

This change resolves Windows logical fonts into local font files and face indexes. It does not implement remote-font downloading, multi-file composite fonts, font rasterization outside NanoVG, or CPU/GPU image mapping. Those concerns remain outside the resolver boundary.

## Alternatives Considered

Extending `acme::node` with DirectWrite would place a text-system dependency below Aura and make a path-oriented platform service responsible for font style selection. A separate resolver factory would isolate the feature but duplicate lifecycle and selection machinery already provided by `write_text`. Storing descriptors only in enumeration items would not support fonts created by family name outside the font list.

The Aura interface with a `write_text_win32` implementation therefore provides the smallest reusable boundary that preserves backend and platform separation.
