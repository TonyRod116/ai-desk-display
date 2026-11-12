"""Previews are limited, local and never contact a physical board."""
import io
import unittest
from PIL import Image
from token_tv.tablet_board import BoardRemote


def png():
    output = io.BytesIO()
    Image.new('RGB', (320, 240), '#386487').save(output, 'PNG')
    return output.getvalue()


class Response(io.BytesIO):
    def __init__(self, data, mime='image/png', length=None):
        super().__init__(data)
        self.status = 200
        self.headers = {'Content-Type': mime, 'Content-Length': str(len(data) if length is None else length)}
    def read1(self, n): return self.read(n)


class Opener:
    def __init__(self, data, mime='image/png', length=None):
        self.data, self.mime, self.length, self.requests = data, mime, length, []
    def open(self, request, timeout):
        self.requests.append((request.full_url, dict(request.header_items()), timeout))
        return Response(self.data, self.mime, self.length)


class PreviewTests(unittest.TestCase):
    def test_reads_exactly_one_fixed_local_preview_route(self):
        opener = Opener(png())
        remote = BoardRemote(opener=opener)
        self.assertEqual(remote.preview(3), png())
        self.assertEqual(opener.requests[0][0], 'http://127.0.0.1:8787/board/preview/3.png')
        self.assertFalse(any(key.lower() in ('cookie','authorization') for key in opener.requests[0][1]))
    def test_bad_indices_are_refused_before_any_request(self):
        opener=Opener(png());remote=BoardRemote(opener=opener)
        for index in (-1,8,True,1.0,'0','../0',None): self.assertIsNone(remote.preview(index))
        self.assertEqual(opener.requests,[])
    def test_a_png_with_extreme_dimensions_is_refused(self):
        data = bytearray(png())
        data[16:20] = (100000).to_bytes(4, 'big')
        self.assertIsNone(BoardRemote(opener=Opener(bytes(data))).preview(0))

    def test_bad_or_oversized_answers_do_not_escape(self):
        for data,mime,length in ((b'<html>SECRET</html>','text/html',None),(b'bad','image/png',None),
                                 (png(),'image/png',600000),(png()+b'x'*600000,'image/png',None)):
            self.assertIsNone(BoardRemote(opener=Opener(data,mime,length)).preview(0))


if __name__ == '__main__': unittest.main()
