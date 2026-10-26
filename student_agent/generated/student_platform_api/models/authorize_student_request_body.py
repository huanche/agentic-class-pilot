from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="AuthorizeStudentRequestBody")



@_attrs_define
class AuthorizeStudentRequestBody:
    """
        Attributes:
            classroom_id (None | str | Unset):
            cookie (None | str | Unset):
            course_id (None | Unset | UUID):
            launch_token (None | str | Unset): 平台签发的课堂进入凭证
     """

    classroom_id: None | str | Unset = UNSET
    cookie: None | str | Unset = UNSET
    course_id: None | Unset | UUID = UNSET
    launch_token: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        classroom_id: None | str | Unset
        if isinstance(self.classroom_id, Unset):
            classroom_id = UNSET
        else:
            classroom_id = self.classroom_id

        cookie: None | str | Unset
        if isinstance(self.cookie, Unset):
            cookie = UNSET
        else:
            cookie = self.cookie

        course_id: None | str | Unset
        if isinstance(self.course_id, Unset):
            course_id = UNSET
        elif isinstance(self.course_id, UUID):
            course_id = str(self.course_id)
        else:
            course_id = self.course_id

        launch_token: None | str | Unset
        if isinstance(self.launch_token, Unset):
            launch_token = UNSET
        else:
            launch_token = self.launch_token


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if classroom_id is not UNSET:
            field_dict["classroom_id"] = classroom_id
        if cookie is not UNSET:
            field_dict["cookie"] = cookie
        if course_id is not UNSET:
            field_dict["course_id"] = course_id
        if launch_token is not UNSET:
            field_dict["launch_token"] = launch_token

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_classroom_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        classroom_id = _parse_classroom_id(d.pop("classroom_id", UNSET))


        def _parse_cookie(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cookie = _parse_cookie(d.pop("cookie", UNSET))


        def _parse_course_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                course_id_type_0 = UUID(data)



                return course_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        course_id = _parse_course_id(d.pop("course_id", UNSET))


        def _parse_launch_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        launch_token = _parse_launch_token(d.pop("launch_token", UNSET))


        authorize_student_request_body = cls(
            classroom_id=classroom_id,
            cookie=cookie,
            course_id=course_id,
            launch_token=launch_token,
        )


        authorize_student_request_body.additional_properties = d
        return authorize_student_request_body

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
