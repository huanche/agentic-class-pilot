from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.report_student_learning_progress_body_event import ReportStudentLearningProgressBodyEvent
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="ReportStudentLearningProgressBody")



@_attrs_define
class ReportStudentLearningProgressBody:
    """
        Attributes:
            course_id (UUID):
            event (ReportStudentLearningProgressBodyEvent):
            user_id (UUID):
            classroom_id (None | str | Unset):
            session_key (None | str | Unset):
     """

    course_id: UUID
    event: ReportStudentLearningProgressBodyEvent
    user_id: UUID
    classroom_id: None | str | Unset = UNSET
    session_key: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        course_id = str(self.course_id)

        event = self.event.value

        user_id = str(self.user_id)

        classroom_id: None | str | Unset
        if isinstance(self.classroom_id, Unset):
            classroom_id = UNSET
        else:
            classroom_id = self.classroom_id

        session_key: None | str | Unset
        if isinstance(self.session_key, Unset):
            session_key = UNSET
        else:
            session_key = self.session_key


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "course_id": course_id,
            "event": event,
            "user_id": user_id,
        })
        if classroom_id is not UNSET:
            field_dict["classroom_id"] = classroom_id
        if session_key is not UNSET:
            field_dict["session_key"] = session_key

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        course_id = UUID(d.pop("course_id"))




        event = ReportStudentLearningProgressBodyEvent(d.pop("event"))




        user_id = UUID(d.pop("user_id"))




        def _parse_classroom_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        classroom_id = _parse_classroom_id(d.pop("classroom_id", UNSET))


        def _parse_session_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        session_key = _parse_session_key(d.pop("session_key", UNSET))


        report_student_learning_progress_body = cls(
            course_id=course_id,
            event=event,
            user_id=user_id,
            classroom_id=classroom_id,
            session_key=session_key,
        )


        report_student_learning_progress_body.additional_properties = d
        return report_student_learning_progress_body

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
