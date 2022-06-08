# totalsize
Script that uses yt-dlp to calculate total size of all videos in a playlist (also works with single videos).
# Installation

```
pip3 install totalsize
```
Totalsize requires python 3.6+.
# Usage

```
usage: totalsize [-h] [-f FORMAT_FILTER] [-m] [-n] [-r NUM] [-c FILE]
                 [--media] [--size] [--duration] [--views] [--likes] [--dislikes] [--percentage]
                 [--cookies FILE] URL
```
See https://github.com/yt-dlp/yt-dlp#format-selection for details on formats.

Specify the `-m` option for additional info on each video.

Specify the `-n` option to suppress output of progress info.

When specifying any of the raw data options, data will always be printed in this order:

*media*, *size*, *duration*, *views*, *likes*, *dislikes*, *percentage*
