from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.platform_learning_context_v1_schema_version import PlatformLearningContextV1SchemaVersion
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.platform_learning_context_v1_publication import PlatformLearningContextV1Publication
  from ..models.platform_learning_context_v1_grounding import PlatformLearningContextV1Grounding
  from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0
  from ..models.platform_learning_context_v1_lesson_catalog_item import PlatformLearningContextV1LessonCatalogItem
  from ..models.platform_learning_context_v1_knowledge_package import PlatformLearningContextV1KnowledgePackage
  from ..models.platform_learning_context_v1_lessons_item import PlatformLearningContextV1LessonsItem





T = TypeVar("T", bound="PlatformLearningContextV1")



@_attrs_define
class PlatformLearningContextV1:
    """ Existing schemaVersion 1 wire format. lessons is optional for legacy consumers; an explicitly empty catalog must
    remain empty. Unknown additive fields are allowed.

        Attributes:
            course_id (UUID):
            knowledge_package (PlatformLearningContextV1KnowledgePackage):
            publication (PlatformLearningContextV1Publication):
            schema_version (PlatformLearningContextV1SchemaVersion):
            user_id (UUID):
            classroom (LearningContextV1ClassroomType0 | None | Unset):
            course_title (str | Unset):
            grounding (PlatformLearningContextV1Grounding | Unset):
            lesson_catalog (list[PlatformLearningContextV1LessonCatalogItem] | Unset):
            lessons (list[PlatformLearningContextV1LessonsItem] | Unset):
            selected_lesson_id (None | str | Unset):
     """

    course_id: UUID
    knowledge_package: PlatformLearningContextV1KnowledgePackage
    publication: PlatformLearningContextV1Publication
    schema_version: PlatformLearningContextV1SchemaVersion
    user_id: UUID
    classroom: LearningContextV1ClassroomType0 | None | Unset = UNSET
    course_title: str | Unset = UNSET
    grounding: PlatformLearningContextV1Grounding | Unset = UNSET
    lesson_catalog: list[PlatformLearningContextV1LessonCatalogItem] | Unset = UNSET
    lessons: list[PlatformLearningContextV1LessonsItem] | Unset = UNSET
    selected_lesson_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_learning_context_v1_publication import PlatformLearningContextV1Publication
        from ..models.platform_learning_context_v1_grounding import PlatformLearningContextV1Grounding
        from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0
        from ..models.platform_learning_context_v1_lesson_catalog_item import PlatformLearningContextV1LessonCatalogItem
        from ..models.platform_learning_context_v1_knowledge_package import PlatformLearningContextV1KnowledgePackage
        from ..models.platform_learning_context_v1_lessons_item import PlatformLearningContextV1LessonsItem
        course_id = str(self.course_id)

        knowledge_package = self.knowledge_package.to_dict()

        publication = self.publication.to_dict()

        schema_version = self.schema_version.value

        user_id = str(self.user_id)

        classroom: dict[str, Any] | None | Unset
        if isinstance(self.classroom, Unset):
            classroom = UNSET
        elif isinstance(self.classroom, LearningContextV1ClassroomType0):
            classroom = self.classroom.to_dict()
        else:
            classroom = self.classroom

        course_title = self.course_title

        grounding: dict[str, Any] | Unset = UNSET
        if not isinstance(self.grounding, Unset):
            grounding = self.grounding.to_dict()

        lesson_catalog: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.lesson_catalog, Unset):
            lesson_catalog = []
            for lesson_catalog_item_data in self.lesson_catalog:
                lesson_catalog_item = lesson_catalog_item_data.to_dict()
                lesson_catalog.append(lesson_catalog_item)



        lessons: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.lessons, Unset):
            lessons = []
            for lessons_item_data in self.lessons:
                lessons_item = lessons_item_data.to_dict()
                lessons.append(lessons_item)



        selected_lesson_id: None | str | Unset
        if isinstance(self.selected_lesson_id, Unset):
            selected_lesson_id = UNSET
        else:
            selected_lesson_id = self.selected_lesson_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "courseId": course_id,
            "knowledgePackage": knowledge_package,
            "publication": publication,
            "schemaVersion": schema_version,
            "userId": user_id,
        })
        if classroom is not UNSET:
            field_dict["classroom"] = classroom
        if course_title is not UNSET:
            field_dict["courseTitle"] = course_title
        if grounding is not UNSET:
            field_dict["grounding"] = grounding
        if lesson_catalog is not UNSET:
            field_dict["lessonCatalog"] = lesson_catalog
        if lessons is not UNSET:
            field_dict["lessons"] = lessons
        if selected_lesson_id is not UNSET:
            field_dict["selectedLessonId"] = selected_lesson_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.platform_learning_context_v1_publication import PlatformLearningContextV1Publication
        from ..models.platform_learning_context_v1_grounding import PlatformLearningContextV1Grounding
        from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0
        from ..models.platform_learning_context_v1_lesson_catalog_item import PlatformLearningContextV1LessonCatalogItem
        from ..models.platform_learning_context_v1_knowledge_package import PlatformLearningContextV1KnowledgePackage
        from ..models.platform_learning_context_v1_lessons_item import PlatformLearningContextV1LessonsItem
        d = dict(src_dict)
        course_id = UUID(d.pop("courseId"))




        knowledge_package = PlatformLearningContextV1KnowledgePackage.from_dict(d.pop("knowledgePackage"))




        publication = PlatformLearningContextV1Publication.from_dict(d.pop("publication"))




        schema_version = PlatformLearningContextV1SchemaVersion(d.pop("schemaVersion"))




        user_id = UUID(d.pop("userId"))




        def _parse_classroom(data: object) -> LearningContextV1ClassroomType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                componentsschemas_learning_context_v1_classroom_type_0 = LearningContextV1ClassroomType0.from_dict(data)



                return componentsschemas_learning_context_v1_classroom_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(LearningContextV1ClassroomType0 | None | Unset, data)

        classroom = _parse_classroom(d.pop("classroom", UNSET))


        course_title = d.pop("courseTitle", UNSET)

        _grounding = d.pop("grounding", UNSET)
        grounding: PlatformLearningContextV1Grounding | Unset
        if isinstance(_grounding,  Unset):
            grounding = UNSET
        else:
            grounding = PlatformLearningContextV1Grounding.from_dict(_grounding)




        _lesson_catalog = d.pop("lessonCatalog", UNSET)
        lesson_catalog: list[PlatformLearningContextV1LessonCatalogItem] | Unset = UNSET
        if _lesson_catalog is not UNSET:
            lesson_catalog = []
            for lesson_catalog_item_data in _lesson_catalog:
                lesson_catalog_item = PlatformLearningContextV1LessonCatalogItem.from_dict(lesson_catalog_item_data)



                lesson_catalog.append(lesson_catalog_item)


        _lessons = d.pop("lessons", UNSET)
        lessons: list[PlatformLearningContextV1LessonsItem] | Unset = UNSET
        if _lessons is not UNSET:
            lessons = []
            for lessons_item_data in _lessons:
                lessons_item = PlatformLearningContextV1LessonsItem.from_dict(lessons_item_data)



                lessons.append(lessons_item)


        def _parse_selected_lesson_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        selected_lesson_id = _parse_selected_lesson_id(d.pop("selectedLessonId", UNSET))


        platform_learning_context_v1 = cls(
            course_id=course_id,
            knowledge_package=knowledge_package,
            publication=publication,
            schema_version=schema_version,
            user_id=user_id,
            classroom=classroom,
            course_title=course_title,
            grounding=grounding,
            lesson_catalog=lesson_catalog,
            lessons=lessons,
            selected_lesson_id=selected_lesson_id,
        )


        platform_learning_context_v1.additional_properties = d
        return platform_learning_context_v1

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
