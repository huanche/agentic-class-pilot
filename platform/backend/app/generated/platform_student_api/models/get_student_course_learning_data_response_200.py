from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_course_learning_data_response_200_sessions_item import GetStudentCourseLearningDataResponse200SessionsItem
  from ..models.get_student_course_learning_data_response_200_event_summary import GetStudentCourseLearningDataResponse200EventSummary
  from ..models.get_student_course_learning_data_response_200_mastery_item import GetStudentCourseLearningDataResponse200MasteryItem





T = TypeVar("T", bound="GetStudentCourseLearningDataResponse200")



@_attrs_define
class GetStudentCourseLearningDataResponse200:
    """
        Attributes:
            event_summary (GetStudentCourseLearningDataResponse200EventSummary):
            mastery (list[GetStudentCourseLearningDataResponse200MasteryItem]):
            sessions (list[GetStudentCourseLearningDataResponse200SessionsItem]):
     """

    event_summary: GetStudentCourseLearningDataResponse200EventSummary
    mastery: list[GetStudentCourseLearningDataResponse200MasteryItem]
    sessions: list[GetStudentCourseLearningDataResponse200SessionsItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_course_learning_data_response_200_sessions_item import GetStudentCourseLearningDataResponse200SessionsItem
        from ..models.get_student_course_learning_data_response_200_event_summary import GetStudentCourseLearningDataResponse200EventSummary
        from ..models.get_student_course_learning_data_response_200_mastery_item import GetStudentCourseLearningDataResponse200MasteryItem
        event_summary = self.event_summary.to_dict()

        mastery = []
        for mastery_item_data in self.mastery:
            mastery_item = mastery_item_data.to_dict()
            mastery.append(mastery_item)



        sessions = []
        for sessions_item_data in self.sessions:
            sessions_item = sessions_item_data.to_dict()
            sessions.append(sessions_item)




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "eventSummary": event_summary,
            "mastery": mastery,
            "sessions": sessions,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_course_learning_data_response_200_sessions_item import GetStudentCourseLearningDataResponse200SessionsItem
        from ..models.get_student_course_learning_data_response_200_event_summary import GetStudentCourseLearningDataResponse200EventSummary
        from ..models.get_student_course_learning_data_response_200_mastery_item import GetStudentCourseLearningDataResponse200MasteryItem
        d = dict(src_dict)
        event_summary = GetStudentCourseLearningDataResponse200EventSummary.from_dict(d.pop("eventSummary"))




        mastery = []
        _mastery = d.pop("mastery")
        for mastery_item_data in (_mastery):
            mastery_item = GetStudentCourseLearningDataResponse200MasteryItem.from_dict(mastery_item_data)



            mastery.append(mastery_item)


        sessions = []
        _sessions = d.pop("sessions")
        for sessions_item_data in (_sessions):
            sessions_item = GetStudentCourseLearningDataResponse200SessionsItem.from_dict(sessions_item_data)



            sessions.append(sessions_item)


        get_student_course_learning_data_response_200 = cls(
            event_summary=event_summary,
            mastery=mastery,
            sessions=sessions,
        )


        get_student_course_learning_data_response_200.additional_properties = d
        return get_student_course_learning_data_response_200

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
