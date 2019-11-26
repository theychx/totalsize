import argparse
import math
import re
import sys
import tempfile
from pathlib import Path

import youtube_dl

DEFAULT_FORMAT = "bestvideo+bestaudio/best"
FORMAT_DOC_URL = "https://github.com/ytdl-org/youtube-dl#format-selection"
FRAGMENTS_REGEX = re.compile(r"range/[\d]+-([\d]+)$")
TEMPPATH = Path(tempfile.gettempdir(), "totalsize", "fragment")
YTDL_OPTS = {"quiet": True, "no_warnings": True, "outtmpl": str(TEMPPATH)}

LINE_LENGTH = 75
TITLE_FIELD_SIZE = LINE_LENGTH - 12
REPORT_TEMPLATE_1 = "{title:<{field_size}}{msg:>12}"
REPORT_TEMPLATE_2 = "{title:<{field_size}} {inaccurate}{size[0]:>7.2f} {size[1]:<2}"
PAD = "-" * LINE_LENGTH
TOTAL_SIZE_TXT = "Total size of all media with reported size"
TOTAL_MEDIA_TXT = "Total number of media files"
TOTAL_INACC_TXT = "Total number of media files with inaccurate reported size"
TOTAL_NO_SIZE_TXT = "Total number of media files with no reported size"


class ResourceNotFoundError(Exception):
    pass


class FormatSelectionError(Exception):
    pass


class Playlist:
    def __init__(self, url, format_sel):
        self._ydl = youtube_dl.YoutubeDL(YTDL_OPTS)
        TEMPPATH.parent.mkdir(exist_ok=True)

        try:
            self._selector = self._ydl.build_format_selector(format_sel)
        except ValueError:
            raise FormatSelectionError

        try:
            preinfo = self._ydl.extract_info(url, process=False)
            if preinfo.get("ie_key"):
                preinfo = self._ydl.extract_info(preinfo["url"], process=False)
        except youtube_dl.utils.DownloadError:
            raise ResourceNotFoundError

        self._medias = preinfo.get("entries") or [preinfo]
        self.number_of_media = self.number_of_media_inacc = self.number_of_media_nosize = self.total_sum = 0

    def _calc_size(self, info):
        media_sum = 0
        inaccurate = False

        for media in info:
            fragments = media.get("fragments")
            if fragments:
                fmatch = re.match(FRAGMENTS_REGEX, fragments[-1]["path"])
                if fmatch:
                    media_sum += int(fmatch.group(1))
                else:
                    fragm_url = media["fragment_base_url"] + fragments[2]["path"]
                    self._ydl.extract_info(fragm_url)
                    media_sum += TEMPPATH.stat().st_size * (len(fragments) - 1)
                    TEMPPATH.unlink()
                    inaccurate = True
            else:
                filesize = media.get("filesize")
                if not filesize:
                    return (False, None)
                media_sum += filesize
        return (inaccurate, media_sum)

    def _get_size(self, info):
        try:
            media = self._ydl.process_ie_result(info, download=False)
        except (youtube_dl.utils.DownloadError, youtube_dl.utils.ExtractorError):
            return (False, None)

        try:
            best = next(self._selector(media))
        except StopIteration:
            raise FormatSelectionError
        except KeyError:
            best = media
        return self._calc_size(best.get("requested_formats") or [best])

    def get_info(self):
        for media in self._medias:
            self.number_of_media += 1
            inaccurate, size = self._get_size(media)
            if inaccurate:
                self.number_of_media_inacc += 1
            if size is None:
                self.number_of_media_nosize += 1
            else:
                self.total_sum += size
            yield (media["title"], inaccurate, size)


def readable_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    ind = int(math.floor(math.log(size_bytes, 1024)))
    pwr = math.pow(1024, ind)
    size = round(size_bytes / pwr, 2)
    return (size, size_name[ind])


def print_report_line(template, title, size=None, inaccurate=False, msg=None, err=False):
    report_line = {
        "title": title[: TITLE_FIELD_SIZE - 3] + "..." if len(title) > TITLE_FIELD_SIZE else title,
        "field_size": TITLE_FIELD_SIZE,
        "msg": msg or ("no size" if size is None else None),
        "inaccurate": "~" if inaccurate else " ",
        "size": readable_size(size) if size else None,
    }
    print(template.format(**report_line), file=sys.stderr if err else sys.stdout)


def get_totalsize(url, format_filter, report_mode=False):
    playlist = Playlist(url, format_filter)
    info = playlist.get_info()

    for title, inaccurate, size in info:
        if not report_mode:
            continue
        if size is None:
            print_report_line(REPORT_TEMPLATE_1, title, size=size, err=True)
        else:
            print_report_line(REPORT_TEMPLATE_2, title, size=size, inaccurate=inaccurate)
    if not report_mode:
        return playlist

    if playlist.total_sum:
        print(PAD)
        print_report_line(
            REPORT_TEMPLATE_2, TOTAL_SIZE_TXT, size=playlist.total_sum, inaccurate=bool(playlist.number_of_media_inacc)
        )

    print(PAD)
    print_report_line(
        REPORT_TEMPLATE_1, TOTAL_MEDIA_TXT, msg=playlist.number_of_media, err=not playlist.number_of_media
    )

    if playlist.number_of_media_inacc:
        print_report_line(REPORT_TEMPLATE_1, TOTAL_INACC_TXT, msg=playlist.number_of_media_inacc)
    if playlist.number_of_media_nosize:
        print_report_line(REPORT_TEMPLATE_1, TOTAL_NO_SIZE_TXT, msg=playlist.number_of_media_nosize, err=True)


def cli():
    parser = argparse.ArgumentParser(description="Calculate total size of media playlist contents.")
    parser.add_argument("url", metavar="URL", type=str, help="playlist/media url")
    parser.add_argument(
        "-f",
        "--format-filter",
        type=str,
        default=DEFAULT_FORMAT,
        help="Custom format filter. See {} for details. The default is {}".format(FORMAT_DOC_URL, DEFAULT_FORMAT),
    )
    args = parser.parse_args()
    err_msg = None

    try:
        get_totalsize(args.url, args.format_filter, report_mode=True)
    except ResourceNotFoundError:
        err_msg = "Resource not found."
    except FormatSelectionError:
        err_msg = "Invalid format filter."
    finally:
        if err_msg:
            parser.error(err_msg)


if __name__ == "__main__":
    cli()
