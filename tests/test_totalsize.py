import sys
import unittest

from totalsize.total import get_totalsize


class TestTotal(unittest.TestCase):
    def test_get_totalsize_yt_channel(self):
        playlist = get_totalsize("https://www.youtube.com/channel/UCvAUb8YbRyXz_l9CXptKoQA/", "18")
        self.assertEqual(playlist.total_sum, 425674114)
        self.assertEqual(playlist.number_of_media, 4)
        self.assertEqual(playlist.number_of_media_inacc, 0)
        self.assertEqual(playlist.number_of_media_nosize, 0)

    def test_get_totalsize_yt_playlist(self):
        playlist = get_totalsize(
            "https://www.youtube.com/watch?v=KIHBpp34JkA&list=PLGx22rG4Cm6dEFvkjmdSRpulz6l0M-g2u", "18"
        )
        self.assertEqual(playlist.total_sum, 197941592)
        self.assertEqual(playlist.number_of_media, 3)
        self.assertEqual(playlist.number_of_media_inacc, 0)
        self.assertEqual(playlist.number_of_media_nosize, 0)

    def test_get_totalsize_yt_video(self):
        playlist = get_totalsize("https://www.youtube.com/watch?v=KIHBpp34JkA", "18")
        self.assertEqual(playlist.total_sum, 69574304)
        self.assertEqual(playlist.number_of_media, 1)
        self.assertEqual(playlist.number_of_media_inacc, 0)
        self.assertEqual(playlist.number_of_media_nosize, 0)


if __name__ == "__main__":
    sys.exit(unittest.main())
