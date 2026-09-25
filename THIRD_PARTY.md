# Third-party components

VultureTracker itself is MIT licensed ([LICENSE](LICENSE)). This lists everything else that ships in the
repository or inside `vulturetracker.exe`, with its license and where the license text lives, followed by
the tools and libraries that are only ever installed and run separately.

`vulturetracker.exe` packs pedalboard (GPL-3.0), so the exe as a whole is distributed under the GPL-3.0
(https://www.gnu.org/licenses/gpl-3.0.html); its corresponding source is this repository at the release's tag plus the
upstream sources linked below. The source code in the repository stays MIT.

## In the repository (`vendor/`) and inside the exe

| Component | Version | License | License text |
|---|---|---|---|
| [libopenmpt](https://lib.openmpt.org) by the OpenMPT Project Developers and Contributors, Olivier Lapicque | 0.8.9 (the DLL 0.8.9+r25651, the WebAssembly build 0.8.9+r25652) | BSD-3-Clause; parts under the Boost Software License 1.0 | `vendor/LICENSE.txt`, `vendor/Licenses/License.mpt.BSD-3-Clause.txt`, `vendor/Licenses/License.mpt.BSL-1.0.txt` |
| mpg123 (`openmpt-mpg123.dll`, as shipped with libopenmpt) | with libopenmpt | LGPL-2.1 (a separate DLL, so it can be replaced; source at https://www.mpg123.de) | `vendor/Licenses/License.mpg123.txt`, authors in `vendor/Licenses/License.mpg123.Authors.txt` |
| libogg (`openmpt-ogg.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.ogg.txt` |
| libvorbis (`openmpt-vorbis.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.Vorbis.txt` |
| zlib (`openmpt-zlib.dll`) by Jean-loup Gailly and Mark Adler | with libopenmpt | zlib License | `vendor/Licenses/License.zlib.txt` |
| libopenmpt compiled to WebAssembly (`vulturetracker/web/libopenmpt.js` + `.wasm`, the official 0.8.9+release dev.js build, for the live engine) | 0.8.9 | BSD-3-Clause and BSL-1.0, with minimp3 (CC0), miniz (MIT) and stb_vorbis (MIT / public domain) compiled in | `vulturetracker/web/licenses/` |

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
