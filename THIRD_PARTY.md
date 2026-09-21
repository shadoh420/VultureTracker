# Third-party components

VultureTracker itself is MIT licensed ([LICENSE](LICENSE)). This lists everything else that ships in the
repository or inside `vulturetracker.exe`, with its license and where the license text lives, followed by
the tools and libraries that are only ever installed and run separately.

## In the repository (`vendor/`) and inside the exe

| Component | Version | License | License text |
|---|---|---|---|
| [libopenmpt](https://lib.openmpt.org) by the OpenMPT Project Developers and Contributors, Olivier Lapicque | LIBOPENMPT_VERSION | BSD-3-Clause; parts under the Boost Software License 1.0 | `vendor/LICENSE.txt`, `vendor/Licenses/License.mpt.BSD-3-Clause.txt`, `vendor/Licenses/License.mpt.BSL-1.0.txt` |
| mpg123 (`openmpt-mpg123.dll`, as shipped with libopenmpt) | with libopenmpt | LGPL-2.1 (a separate DLL, so it can be replaced; source at https://www.mpg123.de) | `vendor/Licenses/License.mpg123.txt`, authors in `vendor/Licenses/License.mpg123.Authors.txt` |
| libogg (`openmpt-ogg.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.ogg.txt` |
| libvorbis (`openmpt-vorbis.dll`) by Xiph.Org | with libopenmpt | BSD-3-Clause | `vendor/Licenses/License.Vorbis.txt` |
| zlib (`openmpt-zlib.dll`) by Jean-loup Gailly and Mark Adler | with libopenmpt | zlib License | `vendor/Licenses/License.zlib.txt` |

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
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the bootloader exception (the packed program keeps its own license) | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |

The exe deliberately excludes pedalboard and mido (see below); `synth` and `audition` need a source checkout.

## Installed and run separately, never redistributed here

| Component | License | Role |
|---|---|---|
| [Surge XT](https://surge-synthesizer.github.io) and its factory patches | GPL-3.0 | synth renderer, fetched into `tools/surge-xt/` by `tools/fetch_surge.py`; demo4's beds, motif chords and choir are renders of factory patches (`demo4/kit.yaml`) |
| [Dexed](https://github.com/asb2m10/dexed) | GPL-3.0 | DX7 renderer, fetched by `tools/fetch_instruments.py`. It ships the "SynprezFM" DX7 cartridges by Jean-Marc Desprez (credited in Dexed's README, no license statement); demo3's Rhodes lead and string pad are renders of two of those patches |
| [OB-Xd](https://www.discodsp.com/obxd/) (discoDSP) | GPL-3.0 | Oberheim renderer, installed by `tools/fetch_instruments.py --install-obxd` |
| [pedalboard](https://github.com/spotify/pedalboard) (Spotify) | GPL-3.0 | Python package that hosts the plugins and prints `fx:` chains; optional dependency of the source checkout |
| mido | MIT | Python package for MIDI note events to the plugins; optional dependency |
| Pillow | MIT-CMU | build-time only: `tools/build_exe.py` regenerates the exe icon from `assets/vulturetracker.png` |
| Big Rusty Drums by Karoryfer Samples; VSCO2 Community Edition and VCSL by Versilian Studios | CC0-1.0 | recordings fetched by `tools/fetch_cc0.py`; renders used in demo3 and demo4 are credited in `samples/demo3/ATTRIBUTION.md` and `samples/demo4/ATTRIBUTION.md` |
| MusicRadar SampleRadar drum-machine packs | MusicRadar's royalty-free terms (use in music; no redistribution) | drum hits kept in the gitignored `samples/local/`; never committed |
| OpenMPT test modules | OpenMPT project | downloaded by `tests/fetch_fixtures.py` for the import round-trip test only |
| Unreal Tournament (1999) soundtrack, Epic Games | proprietary | the *reference* demo4 was measured against; no audio from it is included, and [PROVENANCE.md](PROVENANCE.md) lists every derived figure |

The GPL programs above produce audio; their output is the user's, not GPL. The audio rendered from them for the demos is
credited in the `ATTRIBUTION.md` files next to the WAVs.
