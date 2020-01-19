# totalsize
Script that uses youtube-dl to calculate total size of all videos in a playlist (also works with single videos).
# Installation

```
pip3 install totalsize
```
Totalsize requires python 3.6+.
# Usage

```
totalsize [-h] [-f FORMAT_FILTER] [-m] [-r NUM] [-c FILE] [--media]
          [--size] [--duration] [--views] [--likes] [--dislikes]
          [--percentage]
          URL
```
See https://github.com/ytdl-org/youtube-dl#format-selection for details on formats.

Specify the `-m` option for additional info on each video.

When specifying any of the raw data options, data will always be printed in this order:

*media*, *size*, *duration*, *views*, *likes*, *dislikes*, *percentage*
