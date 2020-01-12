import argparse
import datetime
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
MULT_NAMES_BTS = ("B", "KB", "MB", "GB", "TB", "PB")
MULT_NAMES_DEC = ("", "K", "M", "B")

TXT_FIELD_SIZE = 53
MSG_FIELD_SIZE = 12
MORE_FIELD_SIZE = 55
REPORT_STRING = "{txt:<53}{msg:>12}"
SIZE_STRING = "{0:>7.1f} {1}"
SIZE_STRING_NO_MULT = "{0:>7}"
MORE_STRING = "{duration:>19}{views:>9}{likes:>9}{dislikes:>9}{likes_percentage:>9}"
LEGACY = {"txt": "", "msg": "Size"}
MORE_LEGACY = {
    "duration": "Duration",
    "views": "Views",
    "likes": "Likes",
    "dislikes": "Dislikes",
    "likes_percentage": "L/D%",
}
PAD_CHAR = "-"
PAD = PAD_CHAR * (TXT_FIELD_SIZE + MSG_FIELD_SIZE)
MPAD = PAD_CHAR * (TXT_FIELD_SIZE + MSG_FIELD_SIZE + MORE_FIELD_SIZE)
TOTALS = "Totals"
TOTAL_MEDIA_TXT = "Total number of media files"
TOTAL_INACC_TXT = "Total number of media files with inaccurate reported size"
TOTAL_NO_SIZE_TXT = "Total number of media files with no reported size"
ABORT_TXT = "\nAborted by user. Results will be incomplete!"


class ResourceNotFoundError(Exception):
    pass


class FormatSelectionError(Exception):
    pass


class Entry:
    def __init__(self, title, inaccurate, size, duration, views, likes, dislikes):
        self.title = title
        self.inaccurate = inaccurate
        self.size = size
        self.duration = duration
        self.views = views
        self.likes = likes
        self.dislikes = dislikes

    @property
    def truncated_title(self):
        title = self.title
        if title is None:
            return None
        return title[: TXT_FIELD_SIZE - 3] + "..." if len(title) > TXT_FIELD_SIZE else title

    @property
    def likes_percentage(self):
        if self.likes is None or self.dislikes is None or self.likes == self.dislikes == 0:
            return None
        if self.likes == 0:
            return 0
        return (self.likes / (self.likes + self.dislikes)) * 100

    @property
    def readable_size(self):
        return self._readable_amount(self.size, byte=True)

    @property
    def readable_duration(self):
        return str(datetime.timedelta(seconds=round(self.duration))) if self.duration is not None else None

    @property
    def readable_views(self):
        return self._readable_amount(self.views)

    @property
    def readable_likes(self):
        return self._readable_amount(self.likes)

    @property
    def readable_dislikes(self):
        return self._readable_amount(self.dislikes)

    @property
    def readable_likes_percentage(self):
        likes_percentage = self.likes_percentage
        return "{:.1f}%".format(likes_percentage) if likes_percentage is not None else None

    def _readable_amount(self, amount, byte=False):
        if amount is None:
            return None
        mult = 1024 if byte else 1000
        mult_names = MULT_NAMES_BTS if byte else MULT_NAMES_DEC
        if amount == 0:
            return SIZE_STRING_NO_MULT.format(0)

        ind = int(math.floor(math.log(amount, mult)))
        pwr = math.pow(mult, ind)
        mname = mult_names[ind]
        size = round(amount / pwr, ndigits=1) if pwr > 1 else amount
        fstr = SIZE_STRING if mname else SIZE_STRING_NO_MULT
        return fstr.format(size, mname)


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
        self._entries = []

    @property
    def totals(self):
        if not self._entries:
            return None
        info = {
            "title": None,
            "inaccurate": any(e.inaccurate for e in self._entries),
            "size": sum(e.size for e in self._entries if e.size) or None,
            "duration": sum(e.duration for e in self._entries if e.duration) or None,
            "views": sum(e.views for e in self._entries if e.views) or None,
            "likes": sum(e.likes for e in self._entries if e.likes) or None,
            "dislikes": sum(e.dislikes for e in self._entries if e.dislikes) or None,
        }
        return Entry(**info)

    @property
    def number_of_media(self):
        return len(self._entries)

    @property
    def number_of_media_inacc(self):
        return sum(1 for e in self._entries if e.inaccurate)

    @property
    def number_of_media_nosize(self):
        return sum(1 for e in self._entries if e.size is None)

    def accum_info(self):
        for _ in self.gen_info():
            pass

    def gen_info(self):
        for media in self._medias:
            media_info = self._get_media_info(media) or {}
            inaccurate, size = self._get_size(media_info) if media_info else (False, None)
            info = {
                "title": media.get("title"),
                "inaccurate": inaccurate,
                "size": size,
                "duration": media_info.get("duration"),
                "views": media_info.get("view_count"),
                "likes": media_info.get("like_count"),
                "dislikes": media_info.get("dislike_count"),
            }
            entry = Entry(**info)
            self._entries.append(entry)
            yield entry

    def _get_media_info(self, media):
        try:
            return self._ydl.process_ie_result(media, download=False)
        except (youtube_dl.utils.DownloadError, youtube_dl.utils.ExtractorError):
            return None

    def _get_size(self, media_info):
        try:
            best = next(self._selector(media_info))
        except StopIteration:
            raise FormatSelectionError
        except KeyError:
            best = media_info

        return self._calc_size(best.get("requested_formats") or [best])

    def _calc_size(self, info):
        media_sum = 0
        inaccurate = False

        for media in info:
            filesize = media.get("filesize")
            filesize_approx = media.get("filesize_approx")
            fragments = media.get("fragments")

            if filesize:
                media_sum += filesize
            elif filesize_approx:
                media_sum += filesize_approx
                inaccurate = True
            elif fragments:
                try:
                    media_sum += sum(f["filesize"] for f in fragments)
                except KeyError:
                    pass
                else:
                    continue

                fmatch = re.match(FRAGMENTS_REGEX, fragments[-1]["path"])
                if fmatch:
                    media_sum += int(fmatch.group(1))
                else:
                    lfrags = len(fragments)
                    if lfrags < 2:
                        return (False, None)
                    fragm_url = media["fragment_base_url"] + fragments[2 if lfrags > 2 else 1]["path"]
                    try:
                        self._ydl.extract_info(fragm_url)
                    except youtube_dl.utils.DownloadError:
                        return (False, None)
                    media_sum += TEMPPATH.stat().st_size * (lfrags - 1)
                    TEMPPATH.unlink()
                    inaccurate = True
            else:
                return (False, None)
        return (inaccurate, media_sum)


def print_report_line(entry=None, txt="", msg="", more_info=False, err=False):
    fstr = REPORT_STRING
    if entry:
        txt = txt or entry.truncated_title
        if not msg and entry.size:
            inaccurate = "~" if entry.inaccurate else ""
            msg = inaccurate + entry.readable_size

    report_line = {"txt": txt, "msg": msg}
    if more_info:
        report_line.update(
            {
                "duration": entry.readable_duration or "",
                "views": entry.readable_views or "",
                "likes": entry.readable_likes or "",
                "dislikes": entry.readable_dislikes or "",
                "likes_percentage": entry.readable_likes_percentage or "",
            }
        )
        fstr += MORE_STRING
    print(fstr.format(**report_line), file=sys.stderr if err else sys.stdout)


def print_legacy_line(more_info=False):
    fstr = REPORT_STRING
    legacy_line = LEGACY
    if more_info:
        legacy_line.update(MORE_LEGACY)
        fstr += MORE_STRING
    print(fstr.format(**legacy_line))


def print_report(url, format_filter, more_info=False):
    playlist = Playlist(url, format_filter)
    pad = MPAD if more_info else PAD

    print_legacy_line(more_info=more_info)
    print(pad)

    try:
        for entry in playlist.gen_info():
            if entry.size is None:
                print_report_line(entry=entry, msg="no size", more_info=more_info, err=True)
            else:
                print_report_line(entry=entry, more_info=more_info)
    except KeyboardInterrupt:
        print_report_line(txt=ABORT_TXT, err=True)

    print(pad)
    print_legacy_line(more_info=more_info)
    print(pad)
    print_report_line(txt=TOTALS, entry=playlist.totals, more_info=more_info)

    print(pad)
    number_of_media = playlist.number_of_media
    print_report_line(txt=TOTAL_MEDIA_TXT, msg=number_of_media, err=not number_of_media)

    number_of_media_inacc = playlist.number_of_media_inacc
    if number_of_media_inacc:
        print_report_line(txt=TOTAL_INACC_TXT, msg=number_of_media_inacc)

    number_of_media_nosize = playlist.number_of_media_nosize
    if number_of_media_nosize:
        print_report_line(txt=TOTAL_NO_SIZE_TXT, msg=number_of_media_nosize, err=True)


def cli():
    parser = argparse.ArgumentParser(description="Calculate total size of media playlist contents.")
    parser.add_argument("url", metavar="URL", type=str, help="playlist/media url")
    parser.add_argument(
        "-f",
        "--format-filter",
        default=DEFAULT_FORMAT,
        help="Custom format filter. See {} for details. The default is {}".format(FORMAT_DOC_URL, DEFAULT_FORMAT),
    )
    parser.add_argument(
        "-m", "--more-info", action="store_true", help="Display more info on each media file (if available)."
    )
    args = parser.parse_args()
    err_msg = None

    try:
        print_report(args.url, args.format_filter, more_info=args.more_info)
    except ResourceNotFoundError:
        err_msg = "Resource not found."
    except FormatSelectionError:
        err_msg = "Invalid format filter."
    finally:
        if err_msg:
            parser.error(err_msg)


if __name__ == "__main__":
    cli()
