from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from temba.msgs.models import Attachment


class AttachmentStorageNameTest(SimpleTestCase):
    @override_settings(STORAGE_URL="/rp/media")
    @patch("django.core.files.storage.default_storage.delete")
    def test_local_storage_deletes_by_name_under_the_site_path(self, mock_delete):
        Attachment.bulk_delete(
            [
                Attachment("audio/ogg", "https://example.com/rp/media/attachments/3/a%20b.ogg"),
                Attachment("image/jpeg", "/rp/media/attachments/3/c.jpg"),
            ]
        )

        mock_delete.assert_any_call("attachments/3/a b.ogg")
        mock_delete.assert_any_call("attachments/3/c.jpg")
        self.assertEqual(2, mock_delete.call_count)

    @override_settings(STORAGE_URL="http://localhost:9000/temba-default")
    @patch("django.core.files.storage.default_storage.delete")
    def test_object_storage_keeps_the_url_path(self, mock_delete):
        Attachment.bulk_delete([Attachment("image/jpeg", "http://s3.com/attachments/1/c/d%20e.jpg")])

        mock_delete.assert_called_once_with("/attachments/1/c/d e.jpg")

    @override_settings(STORAGE_URL="/rp/media")
    def test_a_file_outside_the_site_path_keeps_its_path(self):
        self.assertEqual("/elsewhere/x.ogg", Attachment._storage_name("https://example.com/elsewhere/x.ogg"))
