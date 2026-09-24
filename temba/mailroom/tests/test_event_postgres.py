from datetime import timedelta
from uuid import UUID, uuid4

from django.test import override_settings
from django.utils import timezone

from temba.flows.models import FlowRun
from temba.mailroom.events import Event
from temba.msgs.models import Msg
from temba.tests import TembaTest
from temba.utils.uuid import uuid7


@override_settings(DYNAMO_TABLE_PREFIX="")
class EventPostgresTest(TembaTest):
    """
    History served from Postgres, which is what happens when DynamoDB isn't configured
    """

    def setUp(self):
        super().setUp()

        self.contact = self.create_contact("Jim", phone="+593979111111")
        self.flow = self.create_flow("Survey")

        t0 = timezone.now() - timedelta(hours=1)
        self.msg_in = self.create_incoming_msg(self.contact, "hello", created_on=t0)
        self.run = FlowRun.objects.create(
            uuid=uuid7(),
            org=self.org,
            flow=self.flow,
            contact=self.contact,
            status=FlowRun.STATUS_COMPLETED,
            session_uuid=uuid4(),
            created_on=t0 + timedelta(minutes=1),
            exited_on=t0 + timedelta(minutes=3),
        )
        self.msg_out = self.create_outgoing_msg(
            self.contact, "thanks", status=Msg.STATUS_DELIVERED, created_on=t0 + timedelta(minutes=2)
        )
        self.ticket = self.create_ticket(
            self.contact, opened_on=t0 + timedelta(minutes=4), closed_on=t0 + timedelta(minutes=5)
        )
        self.hidden = self.create_incoming_msg(self.contact, "deleted", created_on=t0 + timedelta(minutes=6))
        self.hidden.visibility = Msg.VISIBILITY_DELETED_BY_USER
        self.hidden.save(update_fields=("visibility",))

    def get_history(self, *, before=None, after=None, limit=10, ticket=None) -> list:
        return Event.get_by_contact(self.contact, self.admin, before=before, after=after, ticket=ticket, limit=limit)

    def test_newest_first_with_tags(self):
        events = self.get_history(before=UUID(int=(1 << 128) - 1))

        # the deleted message is left out, closings and endings are events of their own
        self.assertEqual(
            ["ticket_closed", "ticket_opened", "run_ended", "msg_created", "run_started", "msg_received"],
            [e["type"] for e in events],
        )

        msg_created = events[3]
        self.assertEqual(str(self.msg_out.uuid), msg_created["msg"]["uuid"])
        self.assertEqual("thanks", msg_created["msg"]["text"])
        self.assertEqual("delivered", msg_created["_status"]["status"])

        run_started, run_ended = events[4], events[2]
        self.assertEqual(str(self.run.uuid), run_started["uuid"])
        self.assertEqual({"uuid": str(self.flow.uuid), "name": "Survey"}, run_ended["flow"])
        self.assertNotEqual(run_started["uuid"], run_ended["uuid"])

        # every event carries a UUID a browser can hand back as a cursor
        for event in events:
            UUID(event["uuid"])

    def test_paging(self):
        newest_first = self.get_history(before=UUID(int=(1 << 128) - 1))

        # paging back from the middle of the list, including from the derived UUID of a run ending
        page = self.get_history(before=UUID(newest_first[1]["uuid"]))
        self.assertEqual([e["uuid"] for e in newest_first[2:]], [e["uuid"] for e in page])

        page = self.get_history(before=UUID(newest_first[2]["uuid"]))
        self.assertEqual([e["uuid"] for e in newest_first[3:]], [e["uuid"] for e in page])

        # and forward from the first message
        page = self.get_history(after=UUID(str(self.msg_in.uuid)))
        self.assertEqual([e["uuid"] for e in reversed(newest_first[:-1])], [e["uuid"] for e in page])

        # a limit is honoured
        page = self.get_history(before=UUID(int=(1 << 128) - 1), limit=2)
        self.assertEqual([e["uuid"] for e in newest_first[:2]], [e["uuid"] for e in page])

        # an unknown cursor starts from the newest events
        page = self.get_history(before=uuid4())
        self.assertEqual([e["uuid"] for e in newest_first], [e["uuid"] for e in page])

    def test_other_contact(self):
        other = self.create_contact("Bob", phone="+593979222222")
        self.create_incoming_msg(other, "not yours")

        events = self.get_history(before=UUID(int=(1 << 128) - 1))
        self.assertNotIn("not yours", [e.get("msg", {}).get("text") for e in events])
