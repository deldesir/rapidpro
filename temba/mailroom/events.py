from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

import iso8601

from temba.users.models import User
from temba.utils import dynamo

# namespace for the UUIDs given to the history events that have no row of their own (a run ending, a ticket
# closing) when history is served from Postgres - see Event._query_history_postgres
_SYNTH_NAMESPACE = NAMESPACE_URL


@dataclass
class EventTag:
    event_uuid: str
    tag: str
    data: dict


class Event:
    """
    Utility class for working with engine events.
    """

    # engine events
    TYPE_AIRTIME_TRANSFERRED = "airtime_transferred"
    TYPE_BROADCAST_CREATED = "broadcast_created"
    TYPE_CALL_CREATED = "call_created"
    TYPE_CALL_MISSED = "call_missed"
    TYPE_CALL_RECEIVED = "call_received"
    TYPE_CHAT_STARTED = "chat_started"
    TYPE_CONTACT_FIELD_CHANGED = "contact_field_changed"
    TYPE_CONTACT_GROUPS_CHANGED = "contact_groups_changed"
    TYPE_CONTACT_LANGUAGE_CHANGED = "contact_language_changed"
    TYPE_CONTACT_NAME_CHANGED = "contact_name_changed"
    TYPE_CONTACT_STATUS_CHANGED = "contact_status_changed"
    TYPE_CONTACT_URNS_CHANGED = "contact_urns_changed"
    TYPE_IVR_CREATED = "ivr_created"
    TYPE_MSG_CREATED = "msg_created"
    TYPE_MSG_RECEIVED = "msg_received"
    TYPE_OPTIN_REQUESTED = "optin_requested"
    TYPE_OPTIN_STARTED = "optin_started"
    TYPE_OPTIN_STOPPED = "optin_stopped"
    TYPE_RUN_STARTED = "run_started"
    TYPE_RUN_ENDED = "run_ended"
    TYPE_TICKET_ASSIGNED = "ticket_assignee_changed"
    TYPE_TICKET_CLOSED = "ticket_closed"
    TYPE_TICKET_NOTE_ADDED = "ticket_note_added"
    TYPE_TICKET_OPENED = "ticket_opened"
    TYPE_TICKET_REOPENED = "ticket_reopened"
    TYPE_TICKET_TOPIC_CHANGED = "ticket_topic_changed"

    # per-ticket detail events which are only shown on the read page of the ticket they belong to, as opposed to the
    # lifecycle events (opened/closed/reopened) which are shown everywhere
    ticket_detail_types = {TYPE_TICKET_ASSIGNED, TYPE_TICKET_NOTE_ADDED, TYPE_TICKET_TOPIC_CHANGED}

    # message statuses in the order a message moves through them - failed and read are terminal. Errored isn't part of
    # that progression: it can be recorded against a message that's already wired or sent, and is followed by a retry
    # which either moves the message on or fails it permanently, so it only counts when it's the most recent status.
    status_ranks = {"wired": 1, "sent": 2, "delivered": 3, "read": 4, "failed": 5}
    status_errored = "errored"

    @classmethod
    def _is_later_status(cls, new: dict, current: dict) -> bool:
        """
        Whether the given new status tag represents a later state of the message than the current one.
        """
        if cls.status_errored in (new["status"], current["status"]):
            new_rank, current_rank = cls.status_ranks.get(new["status"], 0), cls.status_ranks.get(current["status"], 0)

            # errored can't follow delivery, so only competes with wired and sent, and then by which happened last
            if max(new_rank, current_rank) >= cls.status_ranks["delivered"]:
                return new_rank > current_rank
            return iso8601.parse_date(new["created_on"]) > iso8601.parse_date(current["created_on"])

        return cls.status_ranks.get(new["status"], 0) > cls.status_ranks.get(current["status"], 0)

    @classmethod
    def _from_item(cls, contact, item: dict) -> dict:
        assert item["OrgID"] == contact.org_id, "org ID mismatch for contact event"

        data = item.get("Data", {})
        if dataGZ := item.get("DataGZ"):
            data |= dynamo.load_jsongz(dataGZ)

        data["uuid"] = item["SK"][4:]  # remove "evt#" prefix
        return data

    @classmethod
    def _tag_from_item(cls, contact, item: dict) -> EventTag:
        assert item["OrgID"] == contact.org_id, "org ID mismatch for contact event tag"

        # tag SKs are evt#<event-uuid>#<tag> optionally followed by #<qualifier>, e.g. evt#<uuid>#sts#D for a tag that
        # is written per status value rather than overwritten
        return EventTag(event_uuid=item["SK"][4:40], tag=item["SK"][41:].split("#")[0], data=item.get("Data", {}))

    @classmethod
    def get_by_contact(cls, contact, user, *, before: UUID, after: UUID, ticket: UUID, limit: int) -> list[dict]:
        """
        Fetches events for the given contact either before or after the given event UUID.
        """
        assert (before or after) and not (before and after), "must provide either before or after"

        pk = f"con#{contact.uuid}"
        before_sk = f"evt#{before}" if before else None
        after_sk = f"evt#{after}" if after else None
        events, tags = [], []

        def _item(item: dict) -> bool:
            if item["SK"].count("#") == 1:  # item is an event rather than a tag
                event = cls._from_item(contact, item)

                if cls._include_event(event, ticket):
                    events.append(event)
            else:
                tags.append(cls._tag_from_item(contact, item))

            # Keep going until we reach the limit. Note that because tags are interspersed with events, the last fetched
            # event might not have all its tags yet.. but we always fetch one more event than what we return so the
            # possibly incomplete event will be discarded anyway.
            return len(events) < limit

        cls._query_history(pk, after_sk=after_sk, before_sk=before_sk, limit=limit, callback=_item)
        cls._postprocess_events(contact.org, user, events, tags)

        return events

    @classmethod
    def _query_history(cls, pk: str, *, after_sk: str, before_sk: str, limit: int, callback):
        if not dynamo.is_enabled():
            return cls._query_history_postgres(
                pk, after_sk=after_sk, before_sk=before_sk, limit=limit, callback=callback
            )

        num_fetches = 0
        next_start_sk = None
        query = dict(Limit=limit, Select="ALL_ATTRIBUTES")

        if after_sk:
            query.update(
                KeyConditionExpression="PK = :pk AND SK > :after_sk",
                ExpressionAttributeValues={":pk": pk, ":after_sk": after_sk},
                ScanIndexForward=True,
            )
        elif before_sk:
            query.update(
                KeyConditionExpression="PK = :pk AND SK < :before_sk",
                ExpressionAttributeValues={":pk": pk, ":before_sk": before_sk},
                ScanIndexForward=False,
            )

        while True:
            assert num_fetches < 100, "too many fetches for history"

            if next_start_sk:  # pragma: no cover
                query["ExclusiveStartKey"] = {"PK": pk, "SK": next_start_sk}

            response = dynamo.HISTORY.query(**query)
            num_fetches += 1

            for item in response.get("Items", []):
                if not callback(item):
                    return

            next_start_sk = response.get("LastEvaluatedKey", {}).get("SK")
            if not next_start_sk:
                return

    @classmethod
    def _query_history_postgres(cls, pk: str, *, after_sk: str, before_sk: str, limit: int, callback):
        """
        Serves history from Postgres when there's no DynamoDB: the contact's messages, flow runs and tickets are
        merged and handed to the callback as items of the same shape the DynamoDB path produces, so nothing after
        this point knows where they came from. Runs and tickets each produce two events, and the second one (the
        run ending, the ticket closing) has no row of its own, so it gets a UUID derived from its row's.
        """
        from temba.contacts.models import Contact

        contact = Contact.objects.filter(uuid=pk[len("con#") :]).first()
        if not contact:
            return

        cursor = after_sk or before_sk
        cursor_time = cls._cursor_time(contact, cursor[len("evt#") :]) if cursor else None
        before_time = cursor_time if before_sk else None
        after_time = cursor_time if after_sk else None

        events = []
        events.extend(cls._msgs_to_events(contact, before_time, after_time, limit))
        events.extend(cls._runs_to_events(contact, before_time, after_time, limit))
        events.extend(cls._tickets_to_events(contact, before_time, after_time, limit))

        # the id breaks ties between events with the same timestamp so paging never skips or repeats one
        events.sort(key=lambda e: (e["_sort_key"], e["_sort_id"]), reverse=not after_sk)

        for event in events[:limit]:
            data = {k: v for k, v in event.items() if not k.startswith("_sort_")}
            item = {"OrgID": contact.org_id, "PK": pk, "SK": f"evt#{event['uuid']}", "Data": data}
            if not callback(item):
                return

    @staticmethod
    def _run_ended_uuid(run_uuid) -> str:
        return str(uuid5(_SYNTH_NAMESPACE, f"{run_uuid}-end"))

    @staticmethod
    def _ticket_closed_uuid(ticket_uuid) -> str:
        return str(uuid5(_SYNTH_NAMESPACE, f"{ticket_uuid}-close"))

    @classmethod
    def _cursor_time(cls, contact, cursor_uuid: str):
        """
        Resolves a paging cursor - the UUID of an event the browser has already seen - to that event's time. Only
        this contact's rows are consulted, so the derived UUIDs are matched by recomputing them over the contact's
        exited runs and closed tickets, of which there are few.
        """
        from temba.flows.models import FlowRun
        from temba.msgs.models import Msg
        from temba.tickets.models import Ticket

        if ts := Msg.objects.filter(contact=contact, uuid=cursor_uuid).values_list("created_on", flat=True).first():
            return ts
        if ts := FlowRun.objects.filter(contact=contact, uuid=cursor_uuid).values_list("created_on", flat=True).first():
            return ts
        if ts := Ticket.objects.filter(contact=contact, uuid=cursor_uuid).values_list("opened_on", flat=True).first():
            return ts

        for run_uuid, exited_on in FlowRun.objects.filter(contact=contact, exited_on__isnull=False).values_list(
            "uuid", "exited_on"
        ):
            if cls._run_ended_uuid(run_uuid) == cursor_uuid:
                return exited_on

        for ticket_uuid, closed_on in Ticket.objects.filter(contact=contact, closed_on__isnull=False).values_list(
            "uuid", "closed_on"
        ):
            if cls._ticket_closed_uuid(ticket_uuid) == cursor_uuid:
                return closed_on

        return None  # unknown cursor, the query starts from the newest events

    @staticmethod
    def _window(qs, field: str, before_time, after_time, limit: int):
        """
        Applies the paging window and order to a queryset, on the given timestamp field
        """
        if before_time:
            qs = qs.filter(**{f"{field}__lt": before_time})
        elif after_time:
            qs = qs.filter(**{f"{field}__gt": after_time})

        order = (field, "id") if after_time else (f"-{field}", "-id")
        return qs.order_by(*order)[:limit]

    @classmethod
    def _msgs_to_events(cls, contact, before_time, after_time, limit):
        from temba.msgs.models import Msg

        # the statuses the history UI shows, as the DynamoDB path tags them; a message has no status until it has at
        # least been wired
        status_map = {"W": "wired", "S": "sent", "D": "delivered", "R": "read", "E": "errored", "F": "failed"}
        reason_map = {
            Msg.FAILED_ERROR_LIMIT: "error_limit",
            Msg.FAILED_TOO_OLD: "too_old",
            Msg.FAILED_CHANNEL_REMOVED: "channel_removed",
        }

        msgs = Msg.objects.filter(contact=contact, visibility=Msg.VISIBILITY_VISIBLE).select_related("created_by")
        events = []
        for msg in cls._window(msgs, "created_on", before_time, after_time, limit):
            status = None
            if msg.direction == Msg.DIRECTION_OUT and msg.status in status_map:
                status = {
                    "status": status_map[msg.status],
                    "created_on": (msg.sent_on or msg.modified_on or msg.created_on).isoformat(),
                }
                if msg.failed_reason in reason_map:
                    status["reason"] = reason_map[msg.failed_reason]

            events.append(
                {
                    "uuid": str(msg.uuid),
                    "type": cls.TYPE_MSG_RECEIVED if msg.direction == Msg.DIRECTION_IN else cls.TYPE_MSG_CREATED,
                    "created_on": msg.created_on.isoformat(),
                    "occurred_on": msg.created_on.isoformat(),
                    "msg": {"uuid": str(msg.uuid), "text": msg.text, "attachments": msg.attachments or []},
                    "_status": status,
                    "_user": {"uuid": str(msg.created_by.uuid)} if msg.created_by else None,
                    "_sort_key": msg.created_on,
                    "_sort_id": msg.id,
                }
            )
        return events

    @classmethod
    def _runs_to_events(cls, contact, before_time, after_time, limit):
        from temba.flows.models import FlowRun

        runs = FlowRun.objects.filter(contact=contact).select_related("flow")
        events = []
        for run in cls._window(runs, "created_on", before_time, after_time, limit):
            events.append(
                {
                    "uuid": str(run.uuid),
                    "type": cls.TYPE_RUN_STARTED,
                    "created_on": run.created_on.isoformat(),
                    "occurred_on": run.created_on.isoformat(),
                    "flow": {"uuid": str(run.flow.uuid), "name": run.flow.name},
                    "_sort_key": run.created_on,
                    "_sort_id": run.id,
                }
            )

        # endings are windowed on their own time, which can fall on the other side of a cursor from the start
        ended = runs.filter(exited_on__isnull=False)
        for run in cls._window(ended, "exited_on", before_time, after_time, limit):
            events.append(
                {
                    "uuid": cls._run_ended_uuid(run.uuid),
                    "type": cls.TYPE_RUN_ENDED,
                    "created_on": run.exited_on.isoformat(),
                    "occurred_on": run.exited_on.isoformat(),
                    "flow": {"uuid": str(run.flow.uuid), "name": run.flow.name},
                    "status": run.status,
                    "_sort_key": run.exited_on,
                    "_sort_id": run.id,
                }
            )
        return events

    @classmethod
    def _tickets_to_events(cls, contact, before_time, after_time, limit):
        from temba.tickets.models import Ticket

        def ticket_ref(ticket) -> dict:
            return {"uuid": str(ticket.uuid), "topic": {"uuid": str(ticket.topic.uuid), "name": ticket.topic.name}}

        tickets = Ticket.objects.filter(contact=contact).select_related("topic")
        events = []
        for ticket in cls._window(tickets, "opened_on", before_time, after_time, limit):
            events.append(
                {
                    "uuid": str(ticket.uuid),
                    "type": cls.TYPE_TICKET_OPENED,
                    "created_on": ticket.opened_on.isoformat(),
                    "occurred_on": ticket.opened_on.isoformat(),
                    "ticket": ticket_ref(ticket),
                    "_sort_key": ticket.opened_on,
                    "_sort_id": ticket.id,
                }
            )

        closed = tickets.filter(closed_on__isnull=False)
        for ticket in cls._window(closed, "closed_on", before_time, after_time, limit):
            events.append(
                {
                    "uuid": cls._ticket_closed_uuid(ticket.uuid),
                    "type": cls.TYPE_TICKET_CLOSED,
                    "created_on": ticket.closed_on.isoformat(),
                    "occurred_on": ticket.closed_on.isoformat(),
                    "ticket": ticket_ref(ticket),
                    "_sort_key": ticket.closed_on,
                    "_sort_id": ticket.id,
                }
            )
        return events

    @classmethod
    def _include_event(cls, event, ticket_uuid) -> bool:
        if event["type"] in cls.ticket_detail_types:
            # detail events are only included when fetching for the ticket they belong to
            event_ticket_uuid = event.get("ticket_uuid", event.get("ticket", {}).get("uuid"))
            return bool(ticket_uuid) and event_ticket_uuid == str(ticket_uuid)

        return True

    @classmethod
    def _postprocess_events(cls, org, user: User, events: list[dict], tags: list[EventTag]):
        """
        Post-processes a list of events in place with up to date information from the database.
        """

        # inject tags into their corresponding events
        events_by_uuid = {event["uuid"]: event for event in events}
        for tag in tags:
            if event := events_by_uuid.get(tag.event_uuid):
                if tag.tag == "del":
                    event["_deleted"] = tag.data
                elif tag.tag == "sts":
                    # a message can have several status tags (one per status value) as well as a single overwritten
                    # tag from older writers, so we take the one representing the latest state of the message
                    current = event.get("_status")
                    if not current or cls._is_later_status(tag.data, current):
                        event["_status"] = tag.data

        user_uuids = {event["_user"]["uuid"] for event in events if event.get("_user")}
        users_by_uuid = {str(u.uuid): u for u in org.get_users().filter(uuid__in=user_uuids)}

        # TODO build a more generic mechanism for refreshing all references to things like users, flows.. or put that
        # somewhere else entirely?
        for event in events:
            if "_user" in event and event["_user"]:
                if user := users_by_uuid.get(event["_user"]["uuid"]):
                    event["_user"] = user.as_chat_ref()
                else:
                    event["_user"] = None  # user no longer exists

        for event in events:
            if event["type"] in [cls.TYPE_MSG_CREATED, cls.TYPE_MSG_RECEIVED, cls.TYPE_IVR_CREATED]:
                # older events may have attachments stored as objects rather than encoded strings
                if attachments := event["msg"].get("attachments"):
                    event["msg"]["attachments"] = [
                        f"{a['content_type']}:{a['url']}" if isinstance(a, dict) else a for a in attachments
                    ]
