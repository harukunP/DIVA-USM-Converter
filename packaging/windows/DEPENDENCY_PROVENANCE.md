# Windows build dependency provenance

This checkout does not contain Windows FFmpeg binaries or a WannaCRI executable.
WannaCRI is installed as a Python library (`WannaCRI==0.3.3`) from PyPI and is
bundled by PyInstaller. PyPI lists the project as MIT licensed and publishes
these SHA-256 values for the 0.3.3 release:

- `wannacri-0.3.3-py3-none-any.whl`: `3d96b35c9a76632d2e773eeb2372810e854d9d77b381f81dc348d92f9aacde5c`
- `wannacri-0.3.3.tar.gz`: `8c657ab58c4d49314ce6b8dc6334eef83c9fe89e8243ac4b97f3c7e05b718d5c`

PyPI's release metadata says these files were not uploaded through Trusted
Publishing. A matching hash verifies the download against PyPI's published
file, not the identity of its publisher. Check the source repository and
release before relying on the package. The MIT license copy is in
`licenses/WannaCRI-MIT.txt`.

No Windows FFmpeg supplier has been selected or verified in this project. Do
not place arbitrary `ffmpeg.exe` or `ffprobe.exe` files in `vendor/ffmpeg`.
The package must include both executables, every DLL they need, the exact
license texts and notices for that build and enabled libraries, a source
archive or compliant source offer, build/configuration provenance, and a
SHA-256 manifest. Since `libx264` enables GPL components in the normal FFmpeg
configuration, the corresponding FFmpeg build and x264 notices/source must be
handled under applicable GPL terms. The Windows build script checks these
materials and confirms that `ffmpeg -encoders` lists `libx264`; it cannot
independently establish supplier trustworthiness or legal compliance.

References:

- https://pypi.org/project/WannaCRI/
- https://www.ffmpeg.org/legal.html
- https://ffmpeg.org/general.html
