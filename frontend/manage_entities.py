"""Declarative entity specs that drive the /manage page.

Each managed collection is one Entity: table columns plus validated form
fields. The generic panel template renders both, and manage.py wires the
CRUD round-trips — so adding a new managed entity in the future means
adding an Entity here, a Resource in api_client.py and a loader entry in
manage.py. No new HTML or per-form JS.

Validation happens twice: HTML attributes (required/maxlength/pattern)
give instant feedback, and the backend's Pydantic models are the source
of truth — their 422 field errors are rendered next to the inputs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    widget: str = "text"  # text | password | date | checkbox | select | color
    required: bool = True
    maxlength: int | None = None
    pattern: str | None = None
    coerce: str = "str"  # str | int | bool — applied before the API call
    options: str | None = None  # key into the options dict built per entity
    placeholder: str = ""
    help: str = ""
    admin_only: bool = False  # rendered and submitted only for admins
    optional_on_edit: bool = False  # e.g. password: blank keeps the old value


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"  # text | bool | color
    admin_only: bool = False


@dataclass(frozen=True)
class Entity:
    key: str
    title: str
    singular: str
    admin_only: bool
    columns: tuple[Column, ...]
    fields: tuple[FormField, ...]
    delete_confirm: str


ENTITIES: dict[str, Entity] = {
    e.key: e
    for e in [
        Entity(
            key="objects",
            title="Objects",
            singular="object",
            admin_only=False,
            columns=(
                Column("name", "Name"),
                Column("description", "Description"),
                Column("group_name", "Group"),
                Column("owner_name", "Owner", admin_only=True),
            ),
            fields=(
                FormField("name", "Name", maxlength=30),
                FormField("description", "Description", maxlength=255),
                FormField(
                    "group_id", "Group", widget="select", coerce="int",
                    options="groups",
                ),
                FormField(
                    "user_id", "Owner", widget="select", coerce="int",
                    options="users", admin_only=True,
                ),
            ),
            delete_confirm=(
                "Delete this object? All of its absences will be deleted too."
            ),
        ),
        Entity(
            key="absences",
            title="Absences",
            singular="absence",
            admin_only=False,
            columns=(
                Column("object_name", "Who / what"),
                Column("type_name", "Type"),
                Column("abs_date_start", "From"),
                Column("abs_date_end", "To"),
                Column("description", "Description"),
            ),
            fields=(
                FormField(
                    "object_id", "Who / what", widget="select", coerce="int",
                    options="objects",
                ),
                FormField(
                    "type_id", "Type of absence", widget="select", coerce="int",
                    options="types",
                ),
                FormField("abs_date_start", "From", widget="date"),
                FormField("abs_date_end", "To", widget="date"),
                FormField(
                    "description", "Description", required=False, maxlength=150,
                ),
            ),
            delete_confirm="Delete this absence?",
        ),
        Entity(
            key="types",
            title="Absence types",
            singular="absence type",
            admin_only=True,
            columns=(
                Column("name", "Name"),
                Column("color", "Color", kind="color"),
            ),
            fields=(
                FormField("name", "Name", maxlength=50),
                FormField("color", "Color", widget="color", required=False),
            ),
            delete_confirm=(
                "Delete this absence type? All absences of this type will be "
                "deleted too."
            ),
        ),
        Entity(
            key="groups",
            title="Groups",
            singular="group",
            admin_only=True,
            columns=(
                Column("name", "Name"),
                Column("description", "Description"),
            ),
            fields=(
                FormField("name", "Name", maxlength=255),
                FormField("description", "Description", maxlength=255),
            ),
            delete_confirm=(
                "Delete this group? Its objects and their absences will be "
                "deleted too."
            ),
        ),
        Entity(
            key="users",
            title="Users",
            singular="user",
            admin_only=True,
            columns=(
                Column("username", "Username"),
                Column("admin", "Administrator", kind="bool"),
            ),
            fields=(
                FormField(
                    "username", "Username", maxlength=30,
                    pattern=r"[A-Za-z0-9_. -]+",
                ),
                FormField(
                    "password", "Password", widget="password", maxlength=128,
                    optional_on_edit=True,
                    help="At least 6 characters. When editing, leave blank to keep the current password.",
                ),
                FormField(
                    "admin", "Administrator", widget="checkbox", coerce="bool",
                    required=False,
                ),
            ),
            delete_confirm=(
                "Delete this user? Their objects and absences will be deleted "
                "too."
            ),
        ),
        Entity(
            key="holidays",
            title="Public holidays",
            singular="holiday",
            admin_only=True,
            columns=(
                Column("event_date", "Date"),
                Column("description", "Description"),
                Column("country", "Country"),
                Column("recurring", "Every year", kind="bool"),
            ),
            fields=(
                FormField("event_date", "Date", widget="date"),
                FormField(
                    "description", "Description", required=False, maxlength=150,
                ),
                FormField(
                    "country", "Country code", maxlength=4,
                    pattern="[A-Za-z]{2,4}", placeholder="pl",
                ),
                FormField(
                    "recurring", "Repeats every year", widget="checkbox",
                    coerce="bool", required=False,
                ),
            ),
            delete_confirm="Delete this holiday?",
        ),
    ]
}

# Tab order on the page; "members" has a dedicated panel (group membership
# is a mapping, not a flat table).
TABS: list[tuple[str, str, bool]] = [  # (key, label, admin_only)
    ("objects", "Objects", False),
    ("absences", "Absences", False),
    ("types", "Absence types", True),
    ("groups", "Groups", True),
    ("members", "Group members", True),
    ("users", "Users", True),
    ("holidays", "Public holidays", True),
]
