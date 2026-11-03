from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_student_chat_messages_body import GetStudentChatMessagesBody
from ...models.get_student_chat_messages_response_200_item import GetStudentChatMessagesResponse200Item
from typing import cast



def _get_kwargs(
    course_id: str,
    session_key: str,
    *,
    body: GetStudentChatMessagesBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/internal/platform/courses/{course_id}/chat-sessions/{session_key}/messages".format(course_id=course_id,session_key=session_key,),
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | list[GetStudentChatMessagesResponse200Item] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in (_response_200):
            response_200_item = GetStudentChatMessagesResponse200Item.from_dict(response_200_item_data)



            response_200.append(response_200_item)

        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | list[GetStudentChatMessagesResponse200Item]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    course_id: str,
    session_key: str,
    *,
    client: AuthenticatedClient,
    body: GetStudentChatMessagesBody,

) -> Response[Any | list[GetStudentChatMessagesResponse200Item]]:
    """ Messages from one authorized student session

    Args:
        course_id (str):
        session_key (str):
        body (GetStudentChatMessagesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | list[GetStudentChatMessagesResponse200Item]]
     """


    kwargs = _get_kwargs(
        course_id=course_id,
session_key=session_key,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    course_id: str,
    session_key: str,
    *,
    client: AuthenticatedClient,
    body: GetStudentChatMessagesBody,

) -> Any | list[GetStudentChatMessagesResponse200Item] | None:
    """ Messages from one authorized student session

    Args:
        course_id (str):
        session_key (str):
        body (GetStudentChatMessagesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | list[GetStudentChatMessagesResponse200Item]
     """


    return sync_detailed(
        course_id=course_id,
session_key=session_key,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    course_id: str,
    session_key: str,
    *,
    client: AuthenticatedClient,
    body: GetStudentChatMessagesBody,

) -> Response[Any | list[GetStudentChatMessagesResponse200Item]]:
    """ Messages from one authorized student session

    Args:
        course_id (str):
        session_key (str):
        body (GetStudentChatMessagesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | list[GetStudentChatMessagesResponse200Item]]
     """


    kwargs = _get_kwargs(
        course_id=course_id,
session_key=session_key,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    course_id: str,
    session_key: str,
    *,
    client: AuthenticatedClient,
    body: GetStudentChatMessagesBody,

) -> Any | list[GetStudentChatMessagesResponse200Item] | None:
    """ Messages from one authorized student session

    Args:
        course_id (str):
        session_key (str):
        body (GetStudentChatMessagesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | list[GetStudentChatMessagesResponse200Item]
     """


    return (await asyncio_detailed(
        course_id=course_id,
session_key=session_key,
client=client,
body=body,

    )).parsed
