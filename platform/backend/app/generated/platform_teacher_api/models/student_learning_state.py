from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.student_learning_state_status import StudentLearningStateStatus
from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="StudentLearningState")



@_attrs_define
class StudentLearningState:
    """
        Attributes:
            name (str):
            status (StudentLearningStateStatus):
            student_id (str):
            class_name (str | Unset):
            completed_resource_ids (list[str] | Unset):
            ended_count (float | Unset):
            last_active_at (float | Unset):
            learned_lessons (float | Unset):
            progress (float | Unset):
            session_count (float | Unset):
            stars (float | Unset):
            student_number (str | Unset):
            total_lessons (float | Unset):
     """

    name: str
    status: StudentLearningStateStatus
    student_id: str
    class_name: str | Unset = UNSET
    completed_resource_ids: list[str] | Unset = UNSET
    ended_count: float | Unset = UNSET
    last_active_at: float | Unset = UNSET
    learned_lessons: float | Unset = UNSET
    progress: float | Unset = UNSET
    session_count: float | Unset = UNSET
    stars: float | Unset = UNSET
    student_number: str | Unset = UNSET
    total_lessons: float | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        name = self.name

        status = self.status.value

        student_id = self.student_id

        class_name = self.class_name

        completed_resource_ids: list[str] | Unset = UNSET
        if not isinstance(self.completed_resource_ids, Unset):
            completed_resource_ids = self.completed_resource_ids



        ended_count = self.ended_count

        last_active_at = self.last_active_at

        learned_lessons = self.learned_lessons

        progress = self.progress

        session_count = self.session_count

        stars = self.stars

        student_number = self.student_number

        total_lessons = self.total_lessons


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "status": status,
            "studentId": student_id,
        })
        if class_name is not UNSET:
            field_dict["className"] = class_name
        if completed_resource_ids is not UNSET:
            field_dict["completedResourceIds"] = completed_resource_ids
        if ended_count is not UNSET:
            field_dict["endedCount"] = ended_count
        if last_active_at is not UNSET:
            field_dict["lastActiveAt"] = last_active_at
        if learned_lessons is not UNSET:
            field_dict["learnedLessons"] = learned_lessons
        if progress is not UNSET:
            field_dict["progress"] = progress
        if session_count is not UNSET:
            field_dict["sessionCount"] = session_count
        if stars is not UNSET:
            field_dict["stars"] = stars
        if student_number is not UNSET:
            field_dict["studentNumber"] = student_number
        if total_lessons is not UNSET:
            field_dict["totalLessons"] = total_lessons

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        status = StudentLearningStateStatus(d.pop("status"))




        student_id = d.pop("studentId")

        class_name = d.pop("className", UNSET)

        completed_resource_ids = cast(list[str], d.pop("completedResourceIds", UNSET))


        ended_count = d.pop("endedCount", UNSET)

        last_active_at = d.pop("lastActiveAt", UNSET)

        learned_lessons = d.pop("learnedLessons", UNSET)

        progress = d.pop("progress", UNSET)

        session_count = d.pop("sessionCount", UNSET)

        stars = d.pop("stars", UNSET)

        student_number = d.pop("studentNumber", UNSET)

        total_lessons = d.pop("totalLessons", UNSET)

        student_learning_state = cls(
            name=name,
            status=status,
            student_id=student_id,
            class_name=class_name,
            completed_resource_ids=completed_resource_ids,
            ended_count=ended_count,
            last_active_at=last_active_at,
            learned_lessons=learned_lessons,
            progress=progress,
            session_count=session_count,
            stars=stars,
            student_number=student_number,
            total_lessons=total_lessons,
        )


        student_learning_state.additional_properties = d
        return student_learning_state

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
