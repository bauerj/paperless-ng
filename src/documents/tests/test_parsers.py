import os
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import TestCase

from documents.parsers import get_parser_class, get_supported_file_extensions, get_default_file_extension, \
    get_parser_class_for_mime_type
from paperless_tesseract.parsers import RasterisedDocumentParser
from paperless_text.parsers import TextDocumentParser


def fake_magic_from_file(file, mime=False):

    if mime:
        if os.path.splitext(file)[1] == ".pdf":
            return "application/pdf"
        else:
            return "unknown"
    else:
        return "A verbose string that describes the contents of the file"


@mock.patch("documents.parsers.magic.from_file", fake_magic_from_file)
class TestParserDiscovery(TestCase):

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test__get_parser_class_1_parser(self, m, *args):
        class DummyParser(object):
            pass

        m.return_value = (
            (None, {"weight": 0, "parser": DummyParser, "mime_types": {"application/pdf": ".pdf"}}),
        )

        self.assertEqual(
            get_parser_class("doc.pdf"),
            DummyParser
        )

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test__get_parser_class_n_parsers(self, m, *args):

        class DummyParser1(object):
            pass

        class DummyParser2(object):
            pass

        m.return_value = (
            (None, {"weight": 0, "parser": DummyParser1, "mime_types": {"application/pdf": ".pdf"}}),
            (None, {"weight": 1, "parser": DummyParser2, "mime_types": {"application/pdf": ".pdf"}}),
        )

        self.assertEqual(
            get_parser_class("doc.pdf"),
            DummyParser2
        )

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test__get_parser_class_0_parsers(self, m, *args):
        m.return_value = []
        with TemporaryDirectory() as tmpdir:
            self.assertIsNone(
                get_parser_class("doc.pdf")
            )


class TestParserAvailability(TestCase):

    def test_file_extensions(self):

        for ext in [".pdf", ".jpe", ".jpg", ".jpeg", ".txt", ".csv"]:
            self.assertIn(ext, get_supported_file_extensions())
        self.assertEqual(get_default_file_extension('application/pdf'), ".pdf")
        self.assertEqual(get_default_file_extension('image/png'), ".png")
        self.assertEqual(get_default_file_extension('image/jpeg'), ".jpg")
        self.assertEqual(get_default_file_extension('text/plain'), ".txt")
        self.assertEqual(get_default_file_extension('text/csv'), ".csv")
        self.assertEqual(get_default_file_extension('aasdasd/dgfgf'), None)

        self.assertEqual(get_parser_class_for_mime_type('application/pdf'), RasterisedDocumentParser)
        self.assertEqual(get_parser_class_for_mime_type('text/plain'), TextDocumentParser)
        self.assertEqual(get_parser_class_for_mime_type('text/sdgsdf'), None)
