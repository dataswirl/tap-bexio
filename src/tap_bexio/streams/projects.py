"""Project, time tracking and task streams."""

from __future__ import annotations

from tap_bexio.client import BexioOffsetStream, BexioStream, BexioUnpagedStream


class ProjectsStream(BexioOffsetStream):
    """Projects."""

    name = "projects"
    path = "/2.0/pr_project"
    child_context_key = "project_id"


class ProjectStatesStream(BexioUnpagedStream):
    """Project states."""

    name = "project_states"
    path = "/2.0/pr_project_state"


class ProjectTypesStream(BexioUnpagedStream):
    """Project types."""

    name = "project_types"
    path = "/2.0/pr_project_type"


class ProjectMilestonesStream(BexioOffsetStream):
    """Milestones of a project."""

    name = "project_milestones"
    path = "/3.0/projects/{project_id}/milestones"
    parent_stream_type = ProjectsStream
    state_partitioning_keys = ()


class ProjectPackagesStream(BexioOffsetStream):
    """Work packages of a project."""

    name = "project_packages"
    path = "/3.0/projects/{project_id}/packages"
    parent_stream_type = ProjectsStream
    state_partitioning_keys = ()


class TimesheetsStream(BexioOffsetStream):
    """Timesheet entries."""

    name = "timesheets"
    path = "/2.0/timesheet"


class TimesheetStatusesStream(BexioOffsetStream):
    """Timesheet statuses."""

    name = "timesheet_statuses"
    path = "/2.0/timesheet_status"


class BusinessActivitiesStream(BexioOffsetStream):
    """Business activities (``client_service`` in the API)."""

    name = "business_activities"
    path = "/2.0/client_service"


class TasksStream(BexioOffsetStream):
    """Tasks."""

    name = "tasks"
    path = "/2.0/task"


class TaskPrioritiesStream(BexioOffsetStream):
    """Task priorities."""

    name = "task_priorities"
    path = "/2.0/todo_priority"


class TaskStatusesStream(BexioOffsetStream):
    """Task statuses."""

    name = "task_statuses"
    path = "/2.0/todo_status"


class NotesStream(BexioOffsetStream):
    """Notes."""

    name = "notes"
    path = "/2.0/note"


class CommunicationTypesStream(BexioOffsetStream):
    """Communication types."""

    name = "communication_types"
    path = "/2.0/communication_kind"


STREAMS: list[type[BexioStream]] = [
    ProjectsStream,
    ProjectStatesStream,
    ProjectTypesStream,
    ProjectMilestonesStream,
    ProjectPackagesStream,
    TimesheetsStream,
    TimesheetStatusesStream,
    BusinessActivitiesStream,
    TasksStream,
    TaskPrioritiesStream,
    TaskStatusesStream,
    NotesStream,
    CommunicationTypesStream,
]
