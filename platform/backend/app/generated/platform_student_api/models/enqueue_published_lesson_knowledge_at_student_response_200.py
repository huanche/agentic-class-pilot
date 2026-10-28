from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="EnqueuePublishedLessonKnowledgeAtStudentResponse200")



@_attrs_define
class EnqueuePublishedLessonKnowledgeAtStudentResponse200:
    """
        Attributes:
            course_id (str):
            lesson_id (str):
            video_revision (str):
     """

    course_id: str
    lesson_id: str
    video_revision: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        course_id = self.course_id

        lesson_id = self.lesson_id

        video_revision = self.video_revision


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "courseId": course_id,
            "lessonId": lesson_id,
            "videoRevision": video_revision,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        course_id = d.pop("courseId")

        lesson_id = d.pop("lessonId")

        video_revision = d.pop("videoRevision")

        enqueue_published_lesson_knowledge_at_student_response_200 = cls(
            course_id=course_id,
            lesson_id=lesson_id,
            video_revision=video_revision,
        )


        enqueue_published_lesson_knowledge_at_student_response_200.additional_properties = d
        return enqueue_published_lesson_knowledge_at_student_response_200

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
