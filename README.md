# DIVA-USM-Converter

A Windows utility for converting USM video files to MP4 using FFmpeg.

## Overview

**DIVA-USM-Converter** is a desktop application designed to make USM video conversion easier on Windows. It provides a graphical user interface and uses local FFmpeg tools to process video files.

The project is intended for users working with video files from games, including workflows related to the *Hatsune Miku: Project DIVA* series.

## Features

- **USM to MP4 conversion** — convert supported USM video files into MP4.
- **Graphical user interface** — use the application without manually entering conversion commands.
- **Local video processing** — uses FFmpeg and FFprobe.
- **Windows support** — tested on Windows 10 x64.
- **Portable build testing** — a standalone application build has been tested on an older Windows laptop.

## Requirements

For the prebuilt application, the intended setup is Windows with the required application files included.

For development and building from source, Python and the project's required dependencies are needed.

## Usage

1. Download or obtain a compatible build of DIVA-USM-Converter.
2. Extract the application files if they are provided in an archive.
3. Launch `DIVA-USM-Converter.exe`.
4. Select a supported USM video file.
5. Follow the application's interface to perform the conversion.
6. Check the output MP4 file after conversion.

**Tip:** Keep a backup of your original files before converting them.

## Development Status

The application has been built and tested locally. A test conversion of a two-minute video completed in under one minute on the test computer, with both video and audio working correctly.

Public release packages and distribution documentation are still being prepared.

## Third-Party Software

This project uses FFmpeg and FFprobe for video processing. FFmpeg is a separate open-source project.

Third-party notices, applicable license information, and source-code availability requirements must be reviewed before distributing a packaged build containing FFmpeg.

## Disclaimer

This is an independent project and is not affiliated with or endorsed by SEGA or Crypton Future Media. Project DIVA and Hatsune Miku are mentioned solely to describe the intended use cases.

## License

No license has been specified for this repository yet. Until a license is added, reuse, modification, and redistribution of this project's code are not automatically granted.
