import argparse
import csv
import datetime
import http.cookiejar
import math
import re
import tempfile
import time
from pathlib import Path

import yt_dlp
from prettytable import PrettyTable, SINGLE_BORDER
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

DEFAULT_FORMAT = "bestvideo*+bestaudio/best"
FORMAT_DOC_URL = "https://github.com/yt-dlp/yt-dlp#format-selection"
FRAGMENTS_REGEX = re.compile(r"range/[\d]+-([\d]+)$")
TEMPPATH = Path(tempfile.gettempdir(), "totalsize", "fragment")
TIMEOUT = 30
YTDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "outtmpl": str(TEMPPATH),
    "socket_timeout": TIMEOUT,
}
DEFAULT_RETRIES = 10
MULT_NAMES_BTS = ("B", "KB", "MB", "GB", "TB", "PB")
MULT_NAMES_DEC = ("", "K", "M", "B")
RAW_OPTS = ("media", "size", "duration", "views", "likes", "dislikes", "percentage")
DL_ERRS = ("unable to download webpage", "this video is unavailable", "fragment")
UNSUPPORTED_URL_ERR = "unsupported url"
NOT_AVAILABLE_VAL = -1
CONTENT_FIELDS = ["Id", "Title", "Size"]
CONTENT_MORE_FIELDS = ["Duration", "Views", "Likes", "Dislikes", "Percentage"]
TOTALS_FIELDS = [" ", "Size"]
INFO_FIELDS = ["Info", " "]
TITLE_FIELD_SIZE = 58
SIZE_STRING = "{0:>7.1f} {1}"
SIZE_STRING_NO_MULT = "{0:>7}"
TOTAL_SIZE_TXT = "Total size of media files"
TOTAL_MEDIA_TXT = "Total number of media files"
TOTAL_INACC_TXT = "Total number of media files with inaccurate reported size"
TOTAL_NO_SIZE_TXT = "Total number of media files with no reported size"
ABORT_TXT = "\nAborted by user."
ABORT_INCOMPLETE_TXT = ABORT_TXT + " Results will be incomplete!"
SUPPRESS_TXT = "Suppress normal output, and print raw {}."


class TotalsizeError(Exception):
    pass


class Entry:
    def __init__(self, mid, title, inaccurate, size, duration, views, likes, dislikes):
        self.mid = mid
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
        return title[: TITLE_FIELD_SIZE - 3] + "..." if len(title) > TITLE_FIELD_SIZE else title

    @property
    def likes_percentage(self):
        if self.likes is None or self.dislikes is None:
            return None
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


FAKE_ENTRY = Entry(None, "fake", False, None, None, None, None, None)


class Playlist:
    def __init__(self, url, format_sel, retries=0, cookies_path=None):
        opts = YTDL_OPTS
        if cookies_path:
            opts["cookiefile"] = str(cookies_path)
        self._retries = retries
        self._ydl = yt_dlp.YoutubeDL(opts)
        TEMPPATH.parent.mkdir(exist_ok=True)

        try:
            self._selector = self._ydl.build_format_selector(format_sel)
        except ValueError:
            raise TotalsizeError("Invalid format filter")

        try:
            preinfo = self._ydl.extract_info(url, process=False)
            if preinfo.get("ie_key"):
                preinfo = self._ydl.extract_info(preinfo["url"], process=False)
        except (DownloadError, UnsupportedError):
            raise TotalsizeError("Resource not found")

        self._medias = preinfo.get("entries") or [preinfo]
        self.entries = []

    @property
    def totals(self):
        if not self.entries:
            return FAKE_ENTRY
        info = {
            "mid": None,
            "title": "Totals",
            "inaccurate": any(e.inaccurate for e in self.entries),
            "size": sum(e.size for e in self.entries if e.size) or None,
            "duration": sum(e.duration for e in self.entries if e.duration) or None,
            "views": sum(e.views for e in self.entries if e.views) or None,
            "likes": sum(e.likes for e in self.entries if e.likes) or None,
            "dislikes": sum(e.dislikes for e in self.entries if e.dislikes) or None,
        }
        return Entry(**info)

    @property
    def number_of_media(self):
        return len(self.entries)

    @property
    def number_of_media_inacc(self):
        return sum(1 for e in self.entries if e.inaccurate)

    @property
    def number_of_media_nosize(self):
        return sum(1 for e in self.entries if e.size is None)

    def accum_info(self):
        for _ in self.gen_info():
            pass

    def gen_info(self):
        for media in self._medias:
            attempt_retries = 0
            unsupported = False
            media_info = {}
            inaccurate, size = (False, None)

            while attempt_retries <= self._retries:
                if attempt_retries > 0:
                    time.sleep(TIMEOUT)
                try:
                    media_info = self._get_media_info(media)
                    inaccurate, size = self._get_size(media_info)
                except UnsupportedError:
                    unsupported = True
                    break
                except (DownloadError, ExtractorError) as err:
                    serr = str(err).lower()
                    if any(e in serr for e in DL_ERRS):
                        attempt_retries += 1
                        continue
                    elif UNSUPPORTED_URL_ERR in serr:
                        unsupported = True
                        break
                else:
                    break

            if unsupported:
                continue

            info = {
                "mid": media.get("id"),
                "title": media.get("title"),
                "inaccurate": inaccurate,
                "size": size,
                "duration": media_info.get("duration"),
                "views": media_info.get("view_count"),
                "likes": media_info.get("like_count"),
                "dislikes": media_info.get("dislike_count"),
            }
            self.entries.append(Entry(**info))
            yield 1

    def _get_media_info(self, media):
        return self._ydl.process_ie_result(media, download=False)

    def _get_size(self, media_info):
        try:
            best = next(self._selector(media_info))
        except StopIteration:
            raise TotalsizeError("Invalid format filter")
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
                media_sum += round(filesize_approx)
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
                    self._ydl.extract_info(fragm_url)
                    media_sum += TEMPPATH.stat().st_size * (lfrags - 1)
                    TEMPPATH.unlink()
                    inaccurate = True
            else:
                return (False, None)
        return (inaccurate, media_sum)


def validate_cookiefile(cookies_path):
    if not cookies_path.is_file():
        raise TotalsizeError("Cookie file does not exist")
    try:
        cjar = http.cookiejar.MozillaCookieJar()
        cjar.load(cookies_path, ignore_discard=True, ignore_expires=True)
    except (http.cookiejar.LoadError, UnicodeDecodeError):
        raise TotalsizeError("Cookie file is not formatted correctly")


def gen_csv_rows(entries, more_info=False):
    for entry in entries:
        row = [entry.title, entry.size]
        if more_info:
            row += [entry.duration, entry.views, entry.likes, entry.dislikes, entry.likes_percentage]
        yield row


def write_to_csv(csv_path, rows):
    try:
        with csv_path.open("x", newline="") as csvfile:
            csv_writer = csv.writer(csvfile, quoting=csv.QUOTE_MINIMAL)
            csv_writer.writerows(rows)
    except PermissionError:
        raise TotalsizeError("Insufficient file permissions")
    except FileExistsError:
        raise TotalsizeError("File already exists")
    except FileNotFoundError:
        raise TotalsizeError("Invalid path")


def gen_row(entry, more_info=False):
    row = [entry.mid] if entry.mid else []
    row += [
        entry.truncated_title or "",
        f"{'~' if entry.inaccurate else ' '}{entry.readable_size or 'no size'}",
    ]
    if more_info:
        row += [
            entry.readable_duration or "",
            entry.readable_views or "",
            entry.readable_likes or "",
            entry.readable_dislikes or "",
            entry.readable_likes_percentage or "",
        ]
    return row


def gen_empty_table(fields):
    table = PrettyTable()
    table.align = "r"
    table.set_style(SINGLE_BORDER)
    table.field_names = fields
    return table


def print_report(playlist, more_info=False, no_progress=False):
    interupted = False
    processed_media = 0
    content_fields = CONTENT_FIELDS + CONTENT_MORE_FIELDS if more_info else CONTENT_FIELDS
    content_table = gen_empty_table(content_fields)
    total_fields = TOTALS_FIELDS + CONTENT_MORE_FIELDS if more_info else TOTALS_FIELDS
    totals_table = gen_empty_table(total_fields)

    try:
        for processed in playlist.gen_info():
            processed_media += processed
            if not no_progress:
                print(f"Processed {processed_media} mediafile{'s' if processed_media != 1 else ''}", end="\r")
    except KeyboardInterrupt:
        interupted = True

    if playlist.number_of_media == 0:
        return

    content_table.add_rows([gen_row(e, more_info=more_info) for e in playlist.entries])

    print(content_table)
    if interupted:
        print(ABORT_INCOMPLETE_TXT)

    # Do not display 'totals' and 'info' tables for one video
    if playlist.number_of_media == 1:
        return

    totals_table.add_row(gen_row(playlist.totals, more_info=more_info))
    print(totals_table)

    info_table = gen_empty_table(INFO_FIELDS)
    info_table.add_rows(
        [
            [TOTAL_MEDIA_TXT, playlist.number_of_media],
            [TOTAL_INACC_TXT, playlist.number_of_media_inacc],
            [TOTAL_NO_SIZE_TXT, playlist.number_of_media_nosize],
        ]
    )
    print(info_table)


def print_raw_data(playlist, raw_opts):
    playlist.accum_info()
    totals = playlist.totals
    fields = {
        "media": playlist.number_of_media,
        "size": totals.size or NOT_AVAILABLE_VAL,
        "duration": totals.duration or NOT_AVAILABLE_VAL,
        "views": totals.views if totals.views is not None else NOT_AVAILABLE_VAL,
        "likes": totals.likes if totals.likes is not None else NOT_AVAILABLE_VAL,
        "dislikes": totals.dislikes if totals.dislikes is not None else NOT_AVAILABLE_VAL,
        "percentage": totals.likes_percentage if totals.likes_percentage is not None else NOT_AVAILABLE_VAL,
    }
    for sel_opt in raw_opts:
        print(fields[sel_opt])


def cli():
    parser = argparse.ArgumentParser(description="Calculate total size of media playlist contents.")
    parser.add_argument("url", metavar="URL", type=str, help="playlist/media url")
    parser.add_argument(
        "-f",
        "--format-filter",
        type=str,
        default=DEFAULT_FORMAT,
        help='Custom format filter. See {} for details. The default is "{}".'.format(FORMAT_DOC_URL, DEFAULT_FORMAT),
    )
    parser.add_argument(
        "-m", "--more-info", action="store_true", help="Display more info on each media file (if available)."
    )
    parser.add_argument(
        "-n", "--no-progress", action="store_true", help="Do not display progress count during processing."
    )
    parser.add_argument(
        "-r",
        "--retries",
        metavar="NUM",
        type=int,
        default=DEFAULT_RETRIES,
        help="Max number of connection retries. The default is {}.".format(DEFAULT_RETRIES),
    )
    parser.add_argument("-c", "--csv-file", metavar="FILE", type=str, help="Write data to csv file.")
    parser.add_argument("--media", action="store_true", help=SUPPRESS_TXT.format("media count"))
    parser.add_argument("--size", action="store_true", help=SUPPRESS_TXT.format("total size (bytes)"))
    parser.add_argument("--duration", action="store_true", help=SUPPRESS_TXT.format("total duration (seconds)"))
    parser.add_argument("--views", action="store_true", help=SUPPRESS_TXT.format("views count"))
    parser.add_argument("--likes", action="store_true", help=SUPPRESS_TXT.format("likes count"))
    parser.add_argument("--dislikes", action="store_true", help=SUPPRESS_TXT.format("dislikes count"))
    parser.add_argument("--percentage", action="store_true", help=SUPPRESS_TXT.format("likes/dislikes percentage"))
    parser.add_argument("--cookies", metavar="FILE", default=None, type=str, help="Loads cookie file.")

    args = parser.parse_args()
    err_msg = None

    try:
        csv_path = cookies_path = None
        sel_raw_opts = [key for key, value in vars(args).items() if key in RAW_OPTS and value]
        sorted(sel_raw_opts, key=lambda x: RAW_OPTS.index(x))

        if args.csv_file:
            csv_path = Path(args.csv_file)
            write_to_csv(csv_path, gen_csv_rows([FAKE_ENTRY]))
            csv_path.unlink()

        if args.cookies:
            cookies_path = Path(args.cookies)
            validate_cookiefile(cookies_path)

        playlist = Playlist(args.url, args.format_filter, retries=args.retries, cookies_path=cookies_path)
        if sel_raw_opts:
            print_raw_data(playlist, sel_raw_opts)
        else:
            print_report(playlist, more_info=args.more_info, no_progress=args.no_progress)

        if csv_path:
            write_to_csv(csv_path, gen_csv_rows(playlist.entries, more_info=args.more_info))
    except KeyboardInterrupt:
        err_msg = ABORT_TXT
    except TotalsizeError as err:
        err_msg = str(err)

    if err_msg:
        parser.exit(status=1, message=f"Error: {err_msg}.\n")


if __name__ == "__main__":
    cli()
