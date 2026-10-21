from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.authorize_student_request_response_200_source import AuthorizeStudentRequestResponse200Source
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
  from ..models.authorize_student_request_response_200_publication_type_0 import AuthorizeStudentRequestResponse200PublicationType0





T = TypeVar("T", bound="AuthorizeStudentRequestResponse200")



@_attrs_define
class AuthorizeStudentRequestResponse200:
    """
        Attributes:
            source (AuthorizeStudentRequestResponse200Source):
            user_id (UUID):
            classroom_id (None | str | Unset): launch_token 路径返回
            course_id (UUID | Unset): launch_token 路径返回
            publication (AuthorizeStudentRequestResponse200PublicationType0 | None | Unset): launch_token 路径返回
     """

    source: AuthorizeStudentRequestResponse200Source
    user_id: UUID
    classroom_id: None | str | Unset = UNSET
    course_id: UUID | Unset = UNSET
    publication: AuthorizeStudentRequestResponse200PublicationType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.authorize_student_request_response_200_publication_type_0 import AuthorizeStudentRequestResponse200PublicationType0
        source = self.source.value

        user_id = str(self.user_id)

        classroom_id: None | str | Unset
        if isinstance(self.classroom_id, Unset):
            classroom_id = UNSET
        else:
            classroom_id = self.classroom_id

        course_id: str | Unset = UNSET
        if not isinstance(self.course_id, Unset):
            course_id = str(self.course_id)

        publication: dict[str, Any] | None | Unset
        if isinstance(self.publication, Unset):
            publication = UNSET
        elif isinstance(self.publication, AuthorizeStudentRequestResponse200PublicationType0):
            publication = self.publication.to_dict()
        else:
            publication = self.publication


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "source": source,
            "userId": user_id,
        })
        if classroom_id is not UNSET:
            field_dict["classroomId"] = classroom_id
        if course_id is not UNSET:
            field_dict["courseId"] = course_id
        if publication is not UNSET:
            field_dict["publication"] = publication

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.authorize_student_request_response_200_publication_type_0 import AuthorizeStudentRequestResponse200PublicationType0
        d = dict(src_dict)
        source = AuthorizeStudentRequestResponse200Source(d.pop("source"))




        user_id = UUID(d.pop("userId"))




        def _parse_classroom_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        classroom_id = _parse_classroom_id(d.pop("classroomId", UNSET))


        _course_id = d.pop("courseId", UNSET)
        course_id: UUID | Unset
        if isinstance(_course_id,  Unset):
            course_id = UNSET
        else:
            course_id = UUID(_course_id)




        def _parse_publication(data: object) -> AuthorizeStudentRequestResponse200PublicationType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                publication_type_0 = AuthorizeStudentRequestResponse200PublicationType0.from_dict(data)



                return publication_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuthorizeStudentRequestResponse200PublicationType0 | None | Unset, data)

        publication = _parse_publication(d.pop("publication", UNSET))


        authorize_student_request_response_200 = cls(
            source=source,
            user_id=user_id,
            classroom_id=classroom_id,
            course_id=course_id,
            publication=publication,
        )


        authorize_student_request_response_200.additional_properties = d
        return authorize_student_request_response_200

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
