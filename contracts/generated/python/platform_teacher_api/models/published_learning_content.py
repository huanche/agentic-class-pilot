from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.published_learning_content_course import PublishedLearningContentCourse
  from ..models.published_lesson import PublishedLesson
  from ..models.published_entry import PublishedEntry
  from ..models.published_learning_content_publication import PublishedLearningContentPublication





T = TypeVar("T", bound="PublishedLearningContent")



@_attrs_define
class PublishedLearningContent:
    """
        Attributes:
            course (PublishedLearningContentCourse):
            entries (list[PublishedEntry]):
            lessons (list[PublishedLesson]):
            publication (PublishedLearningContentPublication):
     """

    course: PublishedLearningContentCourse
    entries: list[PublishedEntry]
    lessons: list[PublishedLesson]
    publication: PublishedLearningContentPublication
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_learning_content_course import PublishedLearningContentCourse
        from ..models.published_lesson import PublishedLesson
        from ..models.published_entry import PublishedEntry
        from ..models.published_learning_content_publication import PublishedLearningContentPublication
        course = self.course.to_dict()

        entries = []
        for entries_item_data in self.entries:
            entries_item = entries_item_data.to_dict()
            entries.append(entries_item)



        lessons = []
        for lessons_item_data in self.lessons:
            lessons_item = lessons_item_data.to_dict()
            lessons.append(lessons_item)



        publication = self.publication.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "course": course,
            "entries": entries,
            "lessons": lessons,
            "publication": publication,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_learning_content_course import PublishedLearningContentCourse
        from ..models.published_lesson import PublishedLesson
        from ..models.published_entry import PublishedEntry
        from ..models.published_learning_content_publication import PublishedLearningContentPublication
        d = dict(src_dict)
        course = PublishedLearningContentCourse.from_dict(d.pop("course"))




        entries = []
        _entries = d.pop("entries")
        for entries_item_data in (_entries):
            entries_item = PublishedEntry.from_dict(entries_item_data)



            entries.append(entries_item)


        lessons = []
        _lessons = d.pop("lessons")
        for lessons_item_data in (_lessons):
            lessons_item = PublishedLesson.from_dict(lessons_item_data)



            lessons.append(lessons_item)


        publication = PublishedLearningContentPublication.from_dict(d.pop("publication"))




        published_learning_content = cls(
            course=course,
            entries=entries,
            lessons=lessons,
            publication=publication,
        )


        published_learning_content.additional_properties = d
        return published_learning_content

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
