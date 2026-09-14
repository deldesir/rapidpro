from django.db import migrations

# A label's messages are counted whatever folder they're in, so the count no longer needs to be bucketed by whether
# the message is archived: the labelling triggers count rows without looking up the message, and the message update
# trigger no longer moves counts between buckets when a message changes folder. Existing bucketed rows are left as
# they are - reads have summed across buckets since the bucket stopped meaning anything, and the squasher merges them
# the next time a label's count changes.
SQL = """
----------------------------------------------------------------------
-- Handles DELETE statements on msgs_msg_labels table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_labels_on_delete() RETURNS TRIGGER AS $$
BEGIN
    -- add negative label count for all deleted rows
    INSERT INTO msgs_labelcount("label_id", "count", "is_squashed")
    SELECT label_id, -count(*), FALSE FROM oldtab GROUP BY label_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Handles INSERT statements on msgs_msg_labels table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_labels_on_insert() RETURNS TRIGGER AS $$
BEGIN
    -- add label count for all new rows
    INSERT INTO msgs_labelcount("label_id", "count", "is_squashed")
    SELECT label_id, count(*), FALSE FROM newtab GROUP BY label_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Handles UPDATE statements on msg table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_on_update() RETURNS TRIGGER AS $$
BEGIN
    -- add negative item counts for all rows that belonged to a folder they no longer belong to
    INSERT INTO orgs_itemcount("org_id", "scope", "count", "is_squashed")
    SELECT o.org_id, temba_msg_countscope(o), -count(*), FALSE FROM oldtab o
    INNER JOIN newtab n ON n.id = o.id
    WHERE temba_msg_countscope(o) IS DISTINCT FROM temba_msg_countscope(n) AND temba_msg_countscope(o) IS NOT NULL
    GROUP BY 1, 2;

    -- add positive item counts for all rows that now belong to a folder they didn't belong to
    INSERT INTO orgs_itemcount("org_id", "scope", "count", "is_squashed")
    SELECT n.org_id, temba_msg_countscope(n), count(*), FALSE FROM newtab n
    INNER JOIN oldtab o ON o.id = n.id
    WHERE temba_msg_countscope(o) IS DISTINCT FROM temba_msg_countscope(n) AND temba_msg_countscope(n) IS NOT NULL
    GROUP BY 1, 2;

    -- add new flow activity counts for incoming messages now marked as handled by a flow
    INSERT INTO flows_flowactivitycount("flow_id", "scope", "count", "is_squashed")
    SELECT s.flow_id, unnest(ARRAY[
            format('msgsin:hour:%s', extract(hour FROM NOW())),
            format('msgsin:dow:%s', extract(isodow FROM NOW())),
            format('msgsin:date:%s', NOW()::date)
        ]), s.msgs, FALSE
    FROM (
        SELECT n.flow_id, count(*) AS msgs FROM newtab n INNER JOIN oldtab o ON o.id = n.id
        WHERE n.direction = 'I' AND o.flow_id IS NULL AND n.flow_id IS NOT NULL
        GROUP BY 1
    ) s;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# the previous definitions, which bucketed by folder, so that this can be unapplied
REVERSE_SQL = """
----------------------------------------------------------------------
-- Handles DELETE statements on msgs_msg_labels table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_labels_on_delete() RETURNS TRIGGER AS $$
BEGIN
    -- add negative label count for all deleted rows
    INSERT INTO msgs_labelcount("label_id", "is_archived", "count", "is_squashed")
    SELECT o.label_id, m.folder IN ('A', 'D'), -count(*), FALSE FROM oldtab o
    INNER JOIN msgs_msg m ON m.id = o.msg_id
    GROUP BY o.label_id, m.folder IN ('A', 'D');

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Handles INSERT statements on msgs_msg_labels table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_labels_on_insert() RETURNS TRIGGER AS $$
BEGIN
    -- add label count for all new rows
    INSERT INTO msgs_labelcount("label_id", "is_archived", "count", "is_squashed")
    SELECT n.label_id, m.folder IN ('A', 'D'), count(*), FALSE FROM newtab n
    INNER JOIN msgs_msg m ON m.id = n.msg_id
    GROUP BY n.label_id, m.folder IN ('A', 'D');

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Handles UPDATE statements on msg table
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_msg_on_update() RETURNS TRIGGER AS $$
BEGIN
    -- add negative item counts for all rows that belonged to a folder they no longer belong to
    INSERT INTO orgs_itemcount("org_id", "scope", "count", "is_squashed")
    SELECT o.org_id, temba_msg_countscope(o), -count(*), FALSE FROM oldtab o
    INNER JOIN newtab n ON n.id = o.id
    WHERE temba_msg_countscope(o) IS DISTINCT FROM temba_msg_countscope(n) AND temba_msg_countscope(o) IS NOT NULL
    GROUP BY 1, 2;

    -- add positive item counts for all rows that now belong to a folder they didn't belong to
    INSERT INTO orgs_itemcount("org_id", "scope", "count", "is_squashed")
    SELECT n.org_id, temba_msg_countscope(n), count(*), FALSE FROM newtab n
    INNER JOIN oldtab o ON o.id = n.id
    WHERE temba_msg_countscope(o) IS DISTINCT FROM temba_msg_countscope(n) AND temba_msg_countscope(n) IS NOT NULL
    GROUP BY 1, 2;

    -- add negative old-state label counts for all messages being archived/restored
    INSERT INTO msgs_labelcount("label_id", "is_archived", "count", "is_squashed")
    SELECT ml.label_id, o.folder IN ('A', 'D'), -count(*), FALSE FROM oldtab o
    INNER JOIN newtab n ON n.id = o.id
    INNER JOIN msgs_msg_labels ml ON ml.msg_id = o.id
    WHERE (o.folder NOT IN ('A', 'D') AND n.folder IN ('A', 'D'))
       OR (o.folder IN ('A', 'D') AND n.folder NOT IN ('A', 'D'))
    GROUP BY 1, 2;

    -- add new-state label counts for all messages being archived/restored
    INSERT INTO msgs_labelcount("label_id", "is_archived", "count", "is_squashed")
    SELECT ml.label_id, n.folder IN ('A', 'D'), count(*), FALSE FROM newtab n
    INNER JOIN oldtab o ON o.id = n.id
    INNER JOIN msgs_msg_labels ml ON ml.msg_id = n.id
    WHERE (o.folder NOT IN ('A', 'D') AND n.folder IN ('A', 'D'))
       OR (o.folder IN ('A', 'D') AND n.folder NOT IN ('A', 'D'))
    GROUP BY 1, 2;

    -- add new flow activity counts for incoming messages now marked as handled by a flow
    INSERT INTO flows_flowactivitycount("flow_id", "scope", "count", "is_squashed")
    SELECT s.flow_id, unnest(ARRAY[
            format('msgsin:hour:%s', extract(hour FROM NOW())),
            format('msgsin:dow:%s', extract(isodow FROM NOW())),
            format('msgsin:date:%s', NOW()::date)
        ]), s.msgs, FALSE
    FROM (
        SELECT n.flow_id, count(*) AS msgs FROM newtab n INNER JOIN oldtab o ON o.id = n.id
        WHERE n.direction = 'I' AND o.flow_id IS NULL AND n.flow_id IS NOT NULL
        GROUP BY 1
    ) s;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("msgs", "0318_remove_broadcast_node_uuid"),
    ]

    operations = [
        # the triggers must stop writing the column before it goes
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.RemoveField(
            model_name="labelcount",
            name="is_archived",
        ),
    ]
