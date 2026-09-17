from datetime import datetime, timedelta, timezone as tzone
from unittest.mock import patch

from temba.ivr.models import Call
from temba.tests import TembaTest
from temba.utils.uuid import uuid7


class CallTest(TembaTest):
    def test_model(self):
        contact = self.create_contact("Bob", phone="+123456789")
        call = Call.objects.create(
            uuid=uuid7(),
            org=self.org,
            channel=self.channel,
            direction=Call.DIRECTION_IN,
            contact=contact,
            contact_urn=contact.get_urn(),
            status=Call.STATUS_IN_PROGRESS,
            started_on=datetime(2022, 9, 20, 13, 46, 30, 0, tzone.utc),
        )

        with patch("django.utils.timezone.now", return_value=datetime(2022, 9, 20, 13, 46, 50, 0, tzone.utc)):
            self.assertEqual(timedelta(seconds=20), call.get_duration())  # calculated

        call.duration = 15
        call.status = Call.STATUS_ERRORED
        call.error_reason = Call.ERROR_NOANSWER
        call.save(update_fields=("status", "error_reason"))

        self.assertEqual(timedelta(seconds=15), call.get_duration())  # from duration field

    def test_as_json(self):
        flow = self.create_flow("IVR")
        contact = self.create_contact("Bob", phone="+250788123123")
        call = self.create_incoming_call(flow, contact)

        self.assertEqual(
            {
                "uuid": str(call.uuid),
                "direction": "in",
                "status": "completed",
                "error_reason": None,
                "contact": {"uuid": str(contact.uuid), "name": "Bob"},
                "channel": {"uuid": str(self.channel.uuid), "name": "Test Channel"},
                "duration": 15,
                "created_on": call.created_on.isoformat(),
            },
            call.as_json(),
        )

        # an errored call includes the reason
        call.direction = Call.DIRECTION_OUT
        call.status = Call.STATUS_ERRORED
        call.error_reason = Call.ERROR_NOANSWER
        call.save(update_fields=("direction", "status", "error_reason"))

        as_json = call.as_json()
        self.assertEqual("out", as_json["direction"])
        self.assertEqual("errored", as_json["status"])
        self.assertEqual("no_answer", as_json["error_reason"])

        # a contact without a name is displayed by the URN that was called
        contact.name = ""
        contact.save(update_fields=("name",))
        call.refresh_from_db()

        self.assertEqual({"uuid": str(contact.uuid), "name": "0788 123 123"}, call.as_json()["contact"])

        with self.anonymous(self.org):
            call = Call.objects.select_related("org").get(id=call.id)

            self.assertEqual({"uuid": str(contact.uuid), "name": contact.ref}, call.as_json()["contact"])
