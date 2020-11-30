import filecmp
import os
import shutil
from threading import Thread
from time import sleep
from unittest import mock

from django.conf import settings
from django.core.management import call_command, CommandError
from django.test import override_settings, TransactionTestCase

from documents.models import Tag
from documents.consumer import ConsumerError
from documents.management.commands import document_consumer
from documents.tests.utils import DirectoriesMixin


class ConsumerThread(Thread):

    def __init__(self):
        super().__init__()
        self.cmd = document_consumer.Command()

    def run(self) -> None:
        self.cmd.handle(directory=settings.CONSUMPTION_DIR, oneshot=False)

    def stop(self):
        # Consumer checks this every second.
        self.cmd.stop_flag = True


def chunked(size, source):
    for i in range(0, len(source), size):
        yield source[i:i+size]


class TestConsumerBase(DirectoriesMixin, TransactionTestCase):

    sample_file = os.path.join(os.path.dirname(__file__), "samples", "simple.pdf")

    def setUp(self) -> None:
        super(TestConsumerBase, self).setUp()
        self.t = None
        patcher = mock.patch("documents.management.commands.document_consumer.async_task")
        self.task_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def t_start(self):
        self.t = ConsumerThread()
        self.t.start()
        # give the consumer some time to do initial work
        sleep(1)

    def tearDown(self) -> None:
        if self.t:
            # set the stop flag
            self.t.stop()
            # wait for the consumer to exit.
            self.t.join()

        super(TestConsumerBase, self).tearDown()

    def wait_for_task_mock_call(self):
        n = 0
        while n < 100:
            if self.task_mock.call_count > 0:
                # give task_mock some time to finish and raise errors
                sleep(1)
                return
            n += 1
            sleep(0.1)

    # A bogus async_task that will simply check the file for
    # completeness and raise an exception otherwise.
    def bogus_task(self, func, filename, **kwargs):
        eq = filecmp.cmp(filename, self.sample_file, shallow=False)
        if not eq:
            print("Consumed an INVALID file.")
            raise ConsumerError("Incomplete File READ FAILED")
        else:
            print("Consumed a perfectly valid file.")

    def slow_write_file(self, target, incomplete=False):
        with open(self.sample_file, 'rb') as f:
            pdf_bytes = f.read()

        if incomplete:
            pdf_bytes = pdf_bytes[:len(pdf_bytes) - 100]

        with open(target, 'wb') as f:
            # this will take 2 seconds, since the file is about 20k.
            print("Start writing file.")
            for b in chunked(1000, pdf_bytes):
                f.write(b)
                sleep(0.1)
            print("file completed.")


class TestConsumer(TestConsumerBase):

    def test_consume_file(self):
        self.t_start()

        f = os.path.join(self.dirs.consumption_dir, "my_file.pdf")
        shutil.copy(self.sample_file, f)

        self.wait_for_task_mock_call()

        self.task_mock.assert_called_once()

        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], f)

    def test_consume_existing_file(self):
        f = os.path.join(self.dirs.consumption_dir, "my_file.pdf")
        shutil.copy(self.sample_file, f)

        self.t_start()
        self.task_mock.assert_called_once()

        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], f)

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_pdf(self, error_logger):

        self.task_mock.side_effect = self.bogus_task

        self.t_start()

        fname = os.path.join(self.dirs.consumption_dir, "my_file.pdf")

        self.slow_write_file(fname)

        self.wait_for_task_mock_call()

        error_logger.assert_not_called()

        self.task_mock.assert_called_once()

        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], fname)

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_and_move(self, error_logger):

        self.task_mock.side_effect = self.bogus_task

        self.t_start()

        fname = os.path.join(self.dirs.consumption_dir, "my_file.~df")
        fname2 = os.path.join(self.dirs.consumption_dir, "my_file.pdf")

        self.slow_write_file(fname)
        shutil.move(fname, fname2)

        self.wait_for_task_mock_call()

        self.task_mock.assert_called_once()

        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], fname2)

        error_logger.assert_not_called()

    @mock.patch("documents.management.commands.document_consumer.logger.error")
    def test_slow_write_incomplete(self, error_logger):

        self.task_mock.side_effect = self.bogus_task

        self.t_start()

        fname = os.path.join(self.dirs.consumption_dir, "my_file.pdf")
        self.slow_write_file(fname, incomplete=True)

        self.wait_for_task_mock_call()

        self.task_mock.assert_called_once()
        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], fname)

        # assert that we have an error logged with this invalid file.
        error_logger.assert_called_once()

    @override_settings(CONSUMPTION_DIR="does_not_exist")
    def test_consumption_directory_invalid(self):

        self.assertRaises(CommandError, call_command, 'document_consumer', '--oneshot')

    @override_settings(CONSUMPTION_DIR="")
    def test_consumption_directory_unset(self):

        self.assertRaises(CommandError, call_command, 'document_consumer', '--oneshot')


@override_settings(CONSUMER_POLLING=1)
class TestPollingConsumer(TestConsumer):
    pass


@override_settings(CONSUMER_RECURSIVE=1)
class TestRecursiveConsumer(TestConsumer):
    pass


@override_settings(CONSUMER_RECURSIVE=1)
@override_settings(CONSUMER_POLLING=1)
class TestRecursivePollingConsumer(TestConsumer):
    pass


class TestConsumeWithTags(TestConsumerBase):

    @override_settings(CONSUMER_RECURSIVE=True)
    @override_settings(CONSUMER_SUBDIRS_AS_TAGS=True)
    def test_consume_file_with_path_tags(self):

        tag_names = ("existingTag", "Space Tag")
        # Create a Tag prior to consuming a file using it in path
        tag_ids = [Tag.objects.create(name=tag_names[0]).pk,]

        path = os.path.join(self.dirs.consumption_dir, *tag_names)
        os.makedirs(path, exist_ok=True)

        self.t_start()

        f = os.path.join(path, "my_file.pdf")
        shutil.copy(self.sample_file, f)
        print(f)

        self.wait_for_task_mock_call()

        self.task_mock.assert_called_once()

        # Add the pk of the Tag created by _consume()
        tag_ids.append(Tag.objects.get(name=tag_names[1]).pk)

        args, kwargs = self.task_mock.call_args
        self.assertEqual(args[1], f)

        # assertCountEqual has a bad name, but test that the first
        # sequence contains the same elements as second, regardless of
        # their order.
        self.assertCountEqual(kwargs["override_tag_ids"], tag_ids)

    @override_settings(CONSUMER_RECURSIVE=True)
    @override_settings(CONSUMER_SUBDIRS_AS_TAGS=True)
    def test_created_after_start(self):

        self.t_start()

        tag_names = ("Space Tag", "existingTag")

        path = os.path.join(self.dirs.consumption_dir, *tag_names)
        os.makedirs(path, exist_ok=True)
        sleep(2)
        f = os.path.join(path, "my_file.pdf")
        shutil.copy(self.sample_file, f)
        # the consumer should notice that this directory does exist now and consume the file.

        self.wait_for_task_mock_call()

        self.task_mock.assert_called_once()

    def test_disabled(self):
        self.t_start()

        tag_names = ("Space Tag", "existingTag")

        path = os.path.join(self.dirs.consumption_dir, *tag_names)
        os.makedirs(path, exist_ok=True)
        # this needs to be bigger than 1000, which is the read_delay of inotify.
        sleep(2)
        f = os.path.join(path, "my_file.pdf")
        shutil.copy(self.sample_file, f)
        # the consumer should not see that a file appeared in a subfolder.

        self.wait_for_task_mock_call()

        self.task_mock.assert_not_called()


@override_settings(CONSUMER_POLLING=1)
class TestConsumeWithTagsPolling(TestConsumeWithTags):
    pass
