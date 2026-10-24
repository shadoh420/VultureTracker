# Third-party components

VultureTracker's original code is MIT licensed ([LICENSE](LICENSE)); the source ports listed below retain their
upstream licenses. This lists everything else that ships in the
repository or inside `vulturetracker.exe`, with its license and where the license text lives, followed by
the tools and libraries that are only ever installed and run separately.

`vulturetracker.exe` packs pedalboard (GPL-3.0), so the exe as a whole is distributed under the GPL-3.0
(https://www.gnu.org/licenses/gpl-3.0.html); its corresponding source is this repository at the release's tag plus the
upstream sources linked below. This does not relicense separately licensed source ports or bundled libraries.

## In the repository (`vendor/`) and inside the exe

| Component | Version | License | License text |
|---|---|---|---|
| [libopenmpt](https://lib.openmpt.org) by the OpenMPT Project Developers and Contributors, Olivier Lapicque | 0.8.9 + this repository's native-score patch (DLL and WebAssembly) | BSD-3-Clause; parts under the Boost Software License 1.0 | `vendor/LICENSE.txt`, `vendor/Licenses/License.mpt.BSD-3-Clause.txt`, `vendor/Licenses/License.mpt.BSL-1.0.txt` |
| mpg123 (`openmpt-mpg123.dll`, as shipped with libopenmpt) | with libopenmpt | LGPL-2.1 (a separate DLL, so it can be replaced; source at https://www.mpg123.de) | `vendor/Licenses/License.mpg123.txt`, authors in `vendor/Licenses/License.mpg123.Authors.txt` |
| libogg (`openmpt-ogg.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.ogg.txt` |
| libvorbis (`openmpt-vorbis.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.Vorbis.txt` |
| zlib (`openmpt-zlib.dll`) by Jean-loup Gailly and Mark Adler | with libopenmpt | zlib License | `vendor/Licenses/License.zlib.txt` |
| libopenmpt compiled to WebAssembly (`vulturetracker/web/libopenmpt.js` + `.wasm`, built locally for the live engine) | 0.8.9 + native-score patch; Emscripten 4.0.13 | BSD-3-Clause and BSL-1.0, with minimp3 (CC0), miniz (MIT) and stb_vorbis (MIT / public domain) compiled in | `vulturetracker/web/licenses/` |
| alphaTab (`vulturetracker/web/alphaTab.min.js`), local TAB/score engraving; its audio player is disabled | 1.8.4 | MPL-2.0; bundled component notices remain in the unmodified runtime header | `vulturetracker/web/licenses/alphatab-MPL-2.0.txt` |
| Bravura music font, from alphaTab 1.8.4 | bundled | SIL Open Font License 1.1 | `vulturetracker/web/licenses/Bravura-OFL.txt` |
| Chord theory, recognition and voicing algorithms in `vulturetracker/chord_tools.py`, ported from TuxGuitar by Julian Casadesus, guiv42, helge17 and chord creator Nikola Kolarovic | TuxGuitar `2c46e2a1cccdfdfa6e6f2692f241bd60bf418129`; Python port 2026-10-20 | LGPL-2.1 | `vulturetracker/licenses/TuxGuitar-LGPL-2.1.txt`, `TuxGuitar-AUTHORS.txt`, `TuxGuitar-chord-NOTICE.txt` |
| LilyPond and MusicXML writers in `vulturetracker/notation_export.py` (MusicXML lyrics by Menno Vossen) and the ASCII tablature writer in `vulturetracker/asciitab.py`, ported from TuxGuitar by Julian Casadesus, guiv42 and helge17 | TuxGuitar `2c46e2a1cccdfdfa6e6f2692f241bd60bf418129`; Python ports 2026-10-20 | LGPL-2.1 | `vulturetracker/licenses/TuxGuitar-LGPL-2.1.txt`, `TuxGuitar-AUTHORS.txt`, `TuxGuitar-notation-NOTICE.txt` |
| Scale catalogue and key-signature spelling portions of `vulturetracker/web/tablature.js`, from TuxGuitar by Julian Casadesus, guiv42 and helge17 | TuxGuitar `2c46e2a1cccdfdfa6e6f2692f241bd60bf418129`; JavaScript adaptation 2026-10-20 | LGPL-2.1 for these source-derived portions | `vulturetracker/web/licenses/TuxGuitar-scales-NOTICE.txt`; full LGPL and authors in `vulturetracker/licenses/` |
| Generic priority sorting in `vulturetracker/_java_priority_sort.py`, adapted from OpenJDK TimSort by Josh Bloch, copyright Oracle and Google | OpenJDK `jdk-24+36`; Python adaptation 2026-10-20 | GPL-2.0-only WITH Classpath-exception-2.0; exception retained for this modified sorting library | `vulturetracker/licenses/OpenJDK-TimSort-GPL-2.0-with-classpath.txt`, `OpenJDK-TimSort-NOTICE.txt` |

The chord algorithms' source is the pinned TuxGuitar
[`desktop/TuxGuitar/src/app/tuxguitar/app/view/dialog/chord/`](https://github.com/helge17/tuxguitar/tree/2c46e2a1cccdfdfa6e6f2692f241bd60bf418129/desktop/TuxGuitar/src/app/tuxguitar/app/view/dialog/chord).
The sorting source is OpenJDK's
[`java.util.TimSort`](https://github.com/openjdk/jdk/blob/jdk-24%2B36/src/java.base/share/classes/java/util/TimSort.java).
The sorting library accepts a caller-provided comparator and contains no chord logic or application imports.
It retains its own GPL-2.0-only license and Classpath exception; the independent callers retain their licenses.
The exception's linking permission is used for the combined application, not to relicense the sorting source
under GPL-3.0. The modified Python sources and full notices accompany this repository and are included in the
local package's `source/chord-tools/` folder.

The scale names and interval sets come from the pinned TuxGuitar
`desktop/TuxGuitar/share/scales/scales.xml`; key-signature selection adapts
`common/TuxGuitar-lib/src/main/java/app/tuxguitar/util/TGMusicKeyUtils.java`.
Their source-derived portions retain LGPL-2.1. Editable `tablature.js`, the scale notice, full license and authors
accompany the local package under `source/vulturetracker/`. The remaining original editor code retains MIT.

## Vendored files: digests and sources

The SHA-256 of every third-party file in `vendor/` and `vulturetracker/web/` (a text file hashed with LF line endings, as
git keeps it; a checkout with CRLF endings hashes the same once they are turned back), checked by `tests/test_vendor.py`;
a file added to either folder must be added here. `vulturetracker/web/engine-core.js`, `engine-worklet.js` and
`faust-render.mjs`, `tablature.css` and `score-print.html` are this project's own code (MIT) and are not listed.
The actively maintained `tablature.js` is also outside this digest table; its source-derived scale portions
are attributed above rather than treated as an unmodified vendor bundle.

The unmodified alphaTab browser runtime and Bravura WOFF2 are from the pinned npm package
[`@coderline/alphatab@1.8.4`](https://www.npmjs.com/package/@coderline/alphatab/v/1.8.4), files
`dist/alphaTab.min.js` and `dist/font/Bravura.woff2`. Its matching source is available at
https://github.com/CoderLine/alphaTab/tree/v1.8.4. The font's license comes from that tag's
`packages/alphatab/font/bravura/Bravura-OFL.txt`. These files are served locally; no CDN or renderer soundfont is
used at runtime. The checksums below pin the newly added dependency files for the existing vendor integrity test.

- **Original WebAssembly license source:** https://lib.openmpt.org/files/libopenmpt/dev/libopenmpt-0.8.9+release.dev.js.tar.gz
  (SHA-256 `b2c31cd9c99830997b7a337706509556fd1f5dd27da4b7db62e5a24ec95a2758` for the copy kept in the ignored
  `tools/libopenmpt-js/`; lib.openmpt.org publishes no digests). `licenses/libopenmpt-license.txt` is its
  `license.txt`, the other licenses its `licenses/`; checked byte for byte against that copy on 2026-10-14.
  The runtime files were replaced by the patched build below on 2026-10-20.
- **Original Windows license source:** the license texts accompanying the amd64 DLLs of libopenmpt
  0.8.9+r25651, from lib.openmpt.org's 0.8.9 Windows downloads
  (https://lib.openmpt.org/libopenmpt/download/: `libopenmpt-0.8.9+release.dev.windows.vs2022.zip` and
  `libopenmpt-0.8.9+release.bin.windows.zip` both carry amd64 builds). Which of the two archives the files were taken
  from was not recorded when they were added, so they have not been checked against either; the license digests below
  pin the files as committed. The five DLLs were replaced by the full patched build below on 2026-10-20.

### Patched engine source and reproduction

The corresponding engine source is the official **0.8.9+release** source plus
[`tools/native-score-engine.patch`](tools/native-score-engine.patch). The patch adds frame-boundary parent notes,
identity-checked release, same-frame release/attack batches, opt-in exact Classic timing, explicit tail continuation,
same-module playback checkpoints, harmonic voice groups and identity-owned absolute pitch offsets and gain,
shared by native and WASM. Batch attacks at a new row enter the ordinary note-before-effects path; off-grid attacks
inherit the ongoing tick state. The batch interface accepts up to 64 unique attack parents and 256 release identities.
Legacy playback remains the default. The host must cap tail duration; looping voices can otherwise continue indefinitely.
Each module holds one checkpoint of immutable PCM IT playback. Restore assigns fresh voice identities and returns
their mapping to the host; mixer/settings changes invalidate the checkpoint. The host retains its matching event
index, frame and original voice map. Checkpoints cannot be shared between modules or serialized to disk.
The pitch interface accepts finite offsets within +/-12 semitones on a live identity, including released tails.
It preserves sample phase and tracker modulation; zero removes the offset. Hosts dispatch the note batch before
same-frame pitch controls. Note identities are unique across modules within one loaded engine.
The gain interface accepts finite 0..1 on live owned PCM voices, including released tails; 1 is neutral and
0 remains live. It multiplies each final filtered/panned/ramped voice contribution without changing tracker
volume, phase, envelopes or ramp state. Authored MIDI velocity uses velocity/127 after its attack batch and
before pitch controls. Neutral PCM is unchanged. Retired click-suppression offsets retain upstream integer
decay rounding; measured scaling error stayed below 7.85e-7 (bound 258*2^-27), with native/WASM PCM identical.

The group interface accepts up to three ordered layers per parent attack, with the last layer committing the
parent state. Layers share the preceding parent state but keep independent identities, gain and pitch controls.
The next parent attack applies each layer's NNA once; siblings do not trigger duplicate-note actions against
one another. Capacity, partial sample-map and backing conflicts refuse atomically. Hosts initialize the stereo
mixer with a zero-frame read, then make an empty group dispatch to prepare private rollback storage. Eligibility
is cached per configuration epoch and subsequent transactions reuse that storage. The user's checkpoint remains
independent. This still copies playback state and visited-row bits per transaction; live timing is not yet measured.

The exact-clock checkpoint/group domain also admits absolute row tempo commands T20..FF (32..255 BPM).
The `vt_held_score` extension adds per-attack hold flags to the same atomic group transaction. A held ordinary
voice survives later attacks on its parent, including its release tail, without NNA/DCT or pool stealing cutting
it. Saved voices retain phase, envelopes, filter and identity controls; parent fader/pan/mute apply to them.
Held parents require explicit single-pitch sources and backing containing only empty/T/V cells. Inherited
sources remain outside this bounded capability. The separate `vt_score_contexts` extension keeps independent
note heads on the same parent, including harmonic layers, repeated attacks and grace/main pairs. The host
opens and closes explicit head identities in the atomic frame transaction; same-head NNA/DCT remains unchanged.
Context parents require explicit sources and empty/T/V backing. Carry envelopes, random instrument volume/pan
and random sample auto-vibrato refuse. Checkpoints preserve head bindings and remap their sounding voice IDs.
Speed remains constant; tempo slides, recall and flow commands refuse. The host sums rational seconds across
tempo segments and rounds each absolute event frame once. Exact-clock seeks carry the same fractional-frame
residual through every tick as continuous playback; legacy seek timing is unchanged. Recreating score voices
still requires checkpoint restore and event replay, since raw module seeking cannot reconstruct host-authored groups.

- [MSVC source archive](https://lib.openmpt.org/files/libopenmpt/src/libopenmpt-0.8.9+release.msvc.zip):
  used for the full Windows target and its bundled mpg123/ogg/vorbis/zlib sources.
- [Makefile source archive](https://lib.openmpt.org/files/libopenmpt/src/libopenmpt-0.8.9+release.makefile.tar.gz):
  used for the WASM build files and Linux CI. The thirteen patched C++ files are identical between the archives after
  newline normalization. The retained patch applies to the unmodified makefile archive; for MSVC's CRLF sources use
  `git apply --ignore-space-change /absolute/path/to/VultureTracker/tools/native-score-engine.patch`.

Windows was built with Visual Studio 2022, MSVC **14.43.34808** and Windows SDK **10.0.22621.0**. From the patched
MSVC source root, in that toolchain's developer command prompt:

```bat
MSBuild.exe build\vs2022win10\libopenmpt.vcxproj /m:1 /p:Configuration=ReleaseShared /p:Platform=x64 /p:SpectreMitigation=false /p:CL_MPCount=1 /v:minimal /nologo
```

The local `Directory.Build.props` also set `ClCompile/MultiProcessorCompilation` to `false` to serialize compilation;
that machine-only setting is excluded from the portable patch. Spectre libraries were unavailable locally. Outputs
are `bin/release/vs2022-win10-shared/amd64/{libopenmpt,openmpt-mpg123,openmpt-ogg,openmpt-vorbis,openmpt-zlib}.dll`.
Use the full `libopenmpt.vcxproj`, not `libopenmpt-small.vcxproj`, to preserve this decoder family.

WASM used Emscripten **4.0.13** (release `32b8ae819674cb42b8ac2191afeb9571e33ad5e2`), GNU make **4.4.1**, Node **24.11.0**
and Python **3.14**, with scratch-local SDK configuration/cache and no global PATH change. The pinned Windows SDK bundle
is [wasm-binaries.zip](https://storage.googleapis.com/webassembly/emscripten-releases-builds/win/32b8ae819674cb42b8ac2191afeb9571e33ad5e2/wasm-binaries.zip).
From the patched makefile source root, with that SDK on the current shell's PATH:

```sh
EMCC_CORES=1 EMCC_BATCH_BUILD=0 BINARYEN_CORES=1 make CONFIG=emscripten EMSCRIPTEN_TARGET=wasm TEST=0 EXAMPLES=0 -j1
```

`EMCC_BATCH_BUILD=0` avoids the Windows command-length failure while building Emscripten's libc. Promote
`bin/libopenmpt.js` and `bin/libopenmpt.wasm` together. Native/WASM score, release-tail and default-ramping PCM comparisons
passed locally; this does not claim byte-reproducible compiler output.

The `tests` and `floor` CI jobs download the pinned makefile archive, apply the retained patch with `patch -p1`, and
build a shared library with `make CONFIG=gcc SHARED_LIB=1 STATIC_LIB=0 OPENMPT123=0 EXAMPLES=0 TEST=0 -j2`.
They set `LIBOPENMPT` to its absolute `bin/libopenmpt.so` path. All three CI jobs set `VT_REQUIRE_NATIVE_SCORE=1`
and `VT_REQUIRE_PITCH=1`, `VT_REQUIRE_GAIN=1`, `VT_REQUIRE_GROUPS=1`;
Windows uses the vendored full DLL. These Linux options were checked against the upstream Makefile, but the Linux
build was not run on the Windows development PC.

| File | SHA-256 | From |
|---|---|---|
| `vulturetracker/web/alphaTab.min.js` | `2d0335501b875453d52359de23cd9cebfcf71aed3d5739f1cf95117acfd52bec` | alphaTab 1.8.4 npm package |
| `vulturetracker/web/Bravura.woff2` | `181e0e7c4889f9ad57dde0a11988fa61b941617aa499ecdb9dfd4713896c2b19` | alphaTab 1.8.4 npm package |
| `vulturetracker/web/licenses/alphatab-MPL-2.0.txt` | `de981130586154b6ce2cf91528b9291789192d62234d0d7e6e41d085b8e1d351` | alphaTab 1.8.4 npm package |
| `vulturetracker/web/licenses/Bravura-OFL.txt` | `c24929be7028026a65ee8894da1e3c36d2a4ccce0548d9ba8ba64509f46319ee` | alphaTab v1.8.4 source tag |
| `vulturetracker/web/licenses/TuxGuitar-scales-NOTICE.txt` | `295f496f612276b3a0a772ce94bf3e82efaebd8d23e8fd48e71230652d42aa9d` | TuxGuitar pinned scale catalogue, spelling adaptation and percussion names notice |
| `vendor/libopenmpt.dll` | `ad1e2457876073efe26069e2371d90c113ac22b6ee9b77d1b648547c810ef994` | patched libopenmpt 0.8.9 full MSVC build above |
| `vendor/LICENSE.txt` | `ceabc562c8cfb3af0d51e94182947c23bde6c18274e2b21585bdde22d2031e9d` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.mpg123.Authors.txt` | `fb18c9abae864a20f691e949e4c7871c79f5f0861b3a3dcaf5881c3c02cf5cc2` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.mpg123.txt` | `c22482728a634a8dfdb4ff72a96d4c1ed64cd8f3e79335c401751ac591609366` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.mpt.BSD-3-Clause.txt` | `ceabc562c8cfb3af0d51e94182947c23bde6c18274e2b21585bdde22d2031e9d` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.mpt.BSL-1.0.txt` | `c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.ogg.txt` | `d2ab5758336489da61c12cc5bb757da5339c4ae9001f9bb0562b4370249af814` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.Vorbis.txt` | `ec1815db59fcd302846df949d7424876cb2e2dc5ed1606c5fb0b36787b1cf43a` | the libopenmpt 0.8.9 Windows build |
| `vendor/Licenses/License.zlib.txt` | `4026d921213bb2e311d8d42b44ef53361c102d5d45ae32f93f8e52eaee8d068f` | the libopenmpt 0.8.9 Windows build |
| `vendor/openmpt-mpg123.dll` | `716626602bb13d14ec3fbe1fb25ade956dc2a22187a6817861c16c98688c54d1` | full MSVC build's bundled mpg123 |
| `vendor/openmpt-ogg.dll` | `746df5e04e8549ee9d7a7d740669640a1b4774daff72a7f6da5870530c14b36a` | full MSVC build's bundled libogg |
| `vendor/openmpt-vorbis.dll` | `bed7ba8ebcc6c4ffc14c1f83d8a72a6530330ca4ac0ca34ffeb3a008834cdd79` | full MSVC build's bundled libvorbis |
| `vendor/openmpt-zlib.dll` | `de42c664d7aba4f9874ed07e3c279e2ab79998dc50dc8a056b4489c2da601070` | full MSVC build's bundled zlib |
| `vulturetracker/web/libopenmpt.js` | `31c9de637c0e2cfde3cfdf0bd680fe5c294abceb7040ef0b26aec9b8bcaf3c65` | patched libopenmpt 0.8.9 / Emscripten 4.0.13 build above |
| `vulturetracker/web/libopenmpt.wasm` | `48ed8ccdae0cc654c5ba2231d075779d25caa3e95ecfd5929222ac2d7da75349` | patched libopenmpt 0.8.9 / Emscripten 4.0.13 build above |
| `vulturetracker/web/licenses/libopenmpt-license.txt` | `ceabc562c8cfb3af0d51e94182947c23bde6c18274e2b21585bdde22d2031e9d` | the libopenmpt 0.8.9 dev.js archive |
| `vulturetracker/web/licenses/license.minimp3.txt` | `6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01` | the libopenmpt 0.8.9 dev.js archive |
| `vulturetracker/web/licenses/license.miniz.txt` | `e2c1aeb66eef9191d8c3feb164db2def2335a61d039bf04ed849f6b042433b30` | the libopenmpt 0.8.9 dev.js archive |
| `vulturetracker/web/licenses/license.mpt.BSD-3-Clause.txt` | `ceabc562c8cfb3af0d51e94182947c23bde6c18274e2b21585bdde22d2031e9d` | the libopenmpt 0.8.9 dev.js archive |
| `vulturetracker/web/licenses/license.mpt.BSL-1.0.txt` | `c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566` | the libopenmpt 0.8.9 dev.js archive |
| `vulturetracker/web/licenses/license.stb_vorbis.txt` | `c09188ae9cde711950ab24031074cbf5ded592a3561d4792436a7d5566b6f305` | the libopenmpt 0.8.9 dev.js archive |

## Algorithms reimplemented in the source (`vulturetracker/sources.py`)

| Algorithm | Copyright | License |
|---|---|---|
| [sfxr](https://www.drpetter.se/project_sfxr.html): its synthesis and its seven generators (the `sfxr:` recipe source) | Copyright (c) 2007 Tomas Pettersson | MIT: the same text as [LICENSE](LICENSE), under that copyright line |
| [PADsynth](https://zynaddsubfx.sourceforge.io/doc/PADsynth/PADsynth.htm), the algorithm (the `additive:` recipe source) | Nasca Octavian Paul | public domain (his page: the algorithm, its examples and implementations "are released under Public Domain") |
| [DrumSynth](https://sourceforge.net/projects/drumsynth/) 2.0 by Paul Kellett (mda-vst.com): its sections and their rendering, from his `ds2wav` and help file (the `drum:` recipe source; no presets are included) | Copyright (c) 2007 Paul Kellett | MIT (his release offers MIT or GPL-2.0-or-later): the same text as [LICENSE](LICENSE), under that copyright line |

## Only inside the exe (Python packages packed by PyInstaller)

| Component | Version | License | License text |
|---|---|---|---|
| Python | 3.14.0 | PSF-2.0 | https://docs.python.org/3/license.html |
| [pywebview](https://pywebview.flowrl.com) | 6.2.1 | BSD-3-Clause | https://github.com/r0x0r/pywebview/blob/master/LICENSE |
| Microsoft WebView2 SDK loader (`Microsoft.Web.WebView2.*.dll`, `WebView2Loader.dll`, inside pywebview; the WebView2 runtime itself is part of Windows/Edge and is not bundled) | with pywebview | Microsoft WebView2 SDK license (redistributable) | https://www.nuget.org/packages/Microsoft.Web.WebView2 (LICENSE.txt) |
| pythonnet | 3.1.0 | MIT | https://github.com/pythonnet/pythonnet/blob/master/LICENSE |
| clr-loader | 0.3.1 | MIT | https://github.com/pythonnet/clr-loader/blob/main/LICENSE |
| cffi | 2.0.0 | MIT | https://github.com/python-cffi/cffi/blob/main/LICENSE |
| proxy_tools | 0.1.0 | MIT | https://github.com/jtushman/proxy_tools |
| bottle | 0.13.4 | MIT | https://github.com/bottlepy/bottle/blob/master/LICENSE |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions/blob/main/LICENSE |
| NumPy | 2.5.2 | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 parts) | https://github.com/numpy/numpy/blob/main/LICENSE.txt |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml/blob/main/LICENSE |
| [pedalboard](https://github.com/spotify/pedalboard) (Spotify), with JUCE compiled in | 0.9.25 | GPL-3.0 | https://github.com/spotify/pedalboard/blob/master/LICENSE (source: the same repository, tag v0.9.25) |
| mido | 1.3.3 | MIT | https://github.com/mido/mido/blob/main/LICENSE |
| sounddevice | 0.5.6 | MIT | https://github.com/spatialaudio/python-sounddevice/blob/master/LICENSE |
| PortAudio (the DLLs in sounddevice's Windows wheel, `_sounddevice_data`) | the wheel's build | MIT-style (PortAudio license) | https://github.com/spatialaudio/portaudio-binaries (the ASIO DLL there also compiles in Steinberg's ASIO SDK, dual-licensed since October 2025 under GPL-3.0 or Steinberg's own license; it ships here under GPL-3.0 with the rest of the exe; the SDK: https://www.steinberg.net/developers/) |
| [PyGuitarPro](https://github.com/Perlence/PyGuitarPro) and attrs, when installed at build time | 0.11, 26.1 | LGPL-3.0, MIT | https://github.com/Perlence/PyGuitarPro/blob/master/LICENSE (source: the same repository); https://github.com/python-attrs/attrs/blob/main/LICENSE. Guitar Pro import only; LGPL-3.0 inside a GPL-3.0 exe: the source links above are the offer |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the bootloader exception (the packed program keeps its own license) | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |

pedalboard and mido host the synths for the app's RECIPE box; the synths themselves are not packed (below). sounddevice and PortAudio are the
RECORD tab's audio input.

## Beside the exe (`dist/ffmpeg.exe`, shipped as its own file)

| Component | Version | License | License text and source |
|---|---|---|---|
| [FFmpeg](https://ffmpeg.org), the "essentials" Windows build by gyan.dev as shipped in imageio-ffmpeg 0.6.0 | 7.1 | GPL-3.0 (built with `--enable-gpl --enable-version3`) | `ffmpeg.exe -L` prints it; source for the build: https://www.gyan.dev/ffmpeg/builds/ and https://github.com/FFmpeg/FFmpeg (tag n7.1). A separate program the app runs for the MP3/OGG/FLAC export; not linked into the exe |

In a source checkout the same binary comes from the `imageio-ffmpeg` package (BSD-2-Clause), or any ffmpeg on PATH.

## Installed and run separately, never redistributed here

The native PowerTab/TablEdit readers (`ptb.py`, `tef.py`, `tab_binary.py`) port the
TuxGuitar 2.1.0 providers under LGPL-2.1-or-later. Their exact pinned source paths
and changes are recorded in `vulturetracker/licenses/TuxGuitar-tab-import-NOTICE.txt`;
the local ZIP includes these Python sources and the existing TuxGuitar license/authors.
Batch PDF delivery invokes an installed Edge/Chrome/Chromium in headless mode;
no browser binary or browser automation package is redistributed for that feature.

| Component | License | Role |
|---|---|---|
| [Surge XT](https://surge-synthesizer.github.io) and its factory patches | GPL-3.0 | synth renderer, fetched into `tools/surge-xt/` by `tools/fetch_surge.py` (the exe's RECIPE box downloads the same build into `%LOCALAPPDATA%/VultureTracker/tools/`); demo4's beds, motif chords and choir are renders of factory patches (`demo4/kit.yaml`) |
| [Dexed](https://github.com/asb2m10/dexed) | GPL-3.0 | DX7 renderer, fetched by `tools/fetch_instruments.py` (or by the exe's RECIPE box). It ships the "SynprezFM" DX7 cartridges by Jean-Marc Desprez (credited in Dexed's README, no license statement); demo3's Rhodes lead and string pad are renders of two of those patches |
| [OB-Xd](https://www.discodsp.com/obxd/) (discoDSP) | GPL-3.0 | Oberheim renderer, installed by `tools/fetch_instruments.py --install-obxd` |
| [pedalboard](https://github.com/spotify/pedalboard) (Spotify) and mido | GPL-3.0, MIT | in a source checkout: optional dependencies (`pip install pedalboard mido`); packed inside the exe (above) |
| [PyGuitarPro](https://github.com/Perlence/PyGuitarPro) | LGPL-3.0 | in a source checkout: an optional dependency for the Guitar Pro import (`pip install pyguitarpro`) |
| [faustwasm](https://github.com/grame-cncm/faustwasm) (GRAME: the Faust compiler as WebAssembly, with the Faust libraries in its data file) | LGPL-3.0 (the libraries: mostly LGPL / MIT / STK-4.3, per library) | fetched from npm on request into `tools/faustwasm` (the exe: `%LOCALAPPDATA%/VultureTracker/tools/faustwasm`) by the FAUST tab, the RECIPE box or `faust.fetch()`; serves the FAUST tab and `faust:` recipes; never shipped |
| Pillow | MIT-CMU | build-time only: `tools/build_exe.py` regenerates the exe icon from `assets/vulturetracker.png` |
| Big Rusty Drums by Karoryfer Samples; VSCO2 Community Edition and VCSL by Versilian Studios | CC0-1.0 | recordings fetched by `tools/fetch_cc0.py`; renders used in demo3 and demo4 are credited in `samples/demo3/ATTRIBUTION.md` and `samples/demo4/ATTRIBUTION.md` |
| MusicRadar SampleRadar drum-machine packs | MusicRadar's royalty-free terms (use in music; no redistribution) | drum hits kept in the gitignored `samples/local/`; never committed |
| OpenMPT test modules | OpenMPT project | downloaded by `tests/fetch_fixtures.py` for the import round-trip test only |
| Unreal Tournament (1999) soundtrack, Epic Games | proprietary | the *reference* demo4 was measured against; no audio from it is included, and [PROVENANCE.md](PROVENANCE.md) lists every derived figure |

The GPL programs above produce audio; their output is the user's, not GPL. The audio rendered from them for the demos is
credited in the `ATTRIBUTION.md` files next to the WAVs.
