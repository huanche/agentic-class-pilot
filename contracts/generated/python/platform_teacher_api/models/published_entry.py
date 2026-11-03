from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.published_entry_kind import PublishedEntryKind
from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.published_entry_scope_type_1 import PublishedEntryScopeType1
  from ..models.published_entry_citations_item import PublishedEntryCitationsItem





T = TypeVar("T", bound="PublishedEntry")



@_attrs_define
class PublishedEntry:
    """
        Attributes:
            content (str):
            id (str):
            kind (PublishedEntryKind):
            publication_id (str):
            title (str):
            citations (list[PublishedEntryCitationsItem] | Unset):
            resource_type (None | str | Unset):
            scope (None | PublishedEntryScopeType1 | Unset):
            url (str | Unset):
     """

    content: str
    id: str
    kind: PublishedEntryKind
    publication_id: str
    title: str
    citations: list[PublishedEntryCitationsItem] | Unset = UNSET
    resource_type: None | str | Unset = UNSET
    scope: None | PublishedEntryScopeType1 | Unset = UNSET
    url: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_entry_scope_type_1 import PublishedEntryScopeType1
        from ..models.published_entry_citations_item import PublishedEntryCitationsItem
        content = self.content

        id = self.id

        kind = self.kind.value

        publication_id = self.publication_id

        title = self.title

        citations: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.citations, Unset):
            citations = []
            for citations_item_data in self.citations:
                citations_item = citations_item_data.to_dict()
                citations.append(citations_item)



        resource_type: None | str | Unset
        if isinstance(self.resource_type, Unset):
            resource_type = UNSET
        else:
            resource_type = self.resource_type

        scope: dict[str, Any] | None | Unset
        if isinstance(self.scope, Unset):
            scope = UNSET
        elif isinstance(self.scope, PublishedEntryScopeType1):
            scope = self.scope.to_dict()
        else:
            scope = self.scope

        url = self.url


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "content": content,
            "id": id,
            "kind": kind,
            "publicationId": publication_id,
            "title": title,
        })
        if citations is not UNSET:
            field_dict["citations"] = citations
        if resource_type is not UNSET:
            field_dict["resourceType"] = resource_type
        if scope is not UNSET:
            field_dict["scope"] = scope
        if url is not UNSET:
            field_dict["url"] = url

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_entry_scope_type_1 import PublishedEntryScopeType1
        from ..models.published_entry_citations_item import PublishedEntryCitationsItem
        d = dict(src_dict)
        content = d.pop("content")

        id = d.pop("id")

        kind = PublishedEntryKind(d.pop("kind"))




        publication_id = d.pop("publicationId")

        title = d.pop("title")

        _citations = d.pop("citations", UNSET)
        citations: list[PublishedEntryCitationsItem] | Unset = UNSET
        if _citations is not UNSET:
            citations = []
            for citations_item_data in _citations:
                citations_item = PublishedEntryCitationsItem.from_dict(citations_item_data)



                citations.append(citations_item)


        def _parse_resource_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        resource_type = _parse_resource_type(d.pop("resourceType", UNSET))


        def _parse_scope(data: object) -> None | PublishedEntryScopeType1 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                scope_type_1 = PublishedEntryScopeType1.from_dict(data)



                return scope_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PublishedEntryScopeType1 | Unset, data)

        scope = _parse_scope(d.pop("scope", UNSET))


        url = d.pop("url", UNSET)

        published_entry = cls(
            content=content,
            id=id,
            kind=kind,
            publication_id=publication_id,
            title=title,
            citations=citations,
            resource_type=resource_type,
            scope=scope,
            url=url,
        )


        published_entry.additional_properties = d
        return published_entry

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
