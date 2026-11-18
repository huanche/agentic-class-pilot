from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.enqueue_published_lesson_knowledge_at_student_body_scenes_item import EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem





T = TypeVar("T", bound="EnqueuePublishedLessonKnowledgeAtStudentBody")



@_attrs_define
class EnqueuePublishedLessonKnowledgeAtStudentBody:
    """
        Attributes:
            classroom_id (str):
            course_id (str):
            lesson_id (str):
            scenes (list[EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem]):
            video_revision (str):
     """

    classroom_id: str
    course_id: str
    lesson_id: str
    scenes: list[EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem]
    video_revision: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.enqueue_published_lesson_knowledge_at_student_body_scenes_item import EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem
        classroom_id = self.classroom_id

        course_id = self.course_id

        lesson_id = self.lesson_id

        scenes = []
        for scenes_item_data in self.scenes:
            scenes_item = scenes_item_data.to_dict()
            scenes.append(scenes_item)



        video_revision = self.video_revision


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroomId": classroom_id,
            "courseId": course_id,
            "lessonId": lesson_id,
            "scenes": scenes,
            "videoRevision": video_revision,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.enqueue_published_lesson_knowledge_at_student_body_scenes_item import EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem
        d = dict(src_dict)
        classroom_id = d.pop("classroomId")

        course_id = d.pop("courseId")

        lesson_id = d.pop("lessonId")

        scenes = []
        _scenes = d.pop("scenes")
        for scenes_item_data in (_scenes):
            scenes_item = EnqueuePublishedLessonKnowledgeAtStudentBodyScenesItem.from_dict(scenes_item_data)



            scenes.append(scenes_item)


        video_revision = d.pop("videoRevision")

        enqueue_published_lesson_knowledge_at_student_body = cls(
            classroom_id=classroom_id,
            course_id=course_id,
            lesson_id=lesson_id,
            scenes=scenes,
            video_revision=video_revision,
        )


        enqueue_published_lesson_knowledge_at_student_body.additional_properties = d
        return enqueue_published_lesson_knowledge_at_student_body

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
