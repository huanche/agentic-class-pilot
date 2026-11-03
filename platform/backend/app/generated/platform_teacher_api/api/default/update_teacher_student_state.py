from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.student_learning_state import StudentLearningState
from ...models.update_teacher_student_state_response_200 import UpdateTeacherStudentStateResponse200
from typing import cast



def _get_kwargs(
    course_id: str,
    *,
    body: StudentLearningState,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/classes/{course_id}/students".format(course_id=course_id,),
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | UpdateTeacherStudentStateResponse200 | None:
    if response.status_code == 200:
        response_200 = UpdateTeacherStudentStateResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 400:
        response_400 = cast(Any, None)
        return response_400

    if response.status_code == 401:
        response_401 = cast(Any, None)
        return response_401

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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | UpdateTeacherStudentStateResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    course_id: str,
    *,
    client: AuthenticatedClient,
    body: StudentLearningState,

) -> Response[Any | UpdateTeacherStudentStateResponse200]:
    """
    Args:
        course_id (str):
        body (StudentLearningState):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | UpdateTeacherStudentStateResponse200]
     """


    kwargs = _get_kwargs(
        course_id=course_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    course_id: str,
    *,
    client: AuthenticatedClient,
    body: StudentLearningState,

) -> Any | UpdateTeacherStudentStateResponse200 | None:
    """
    Args:
        course_id (str):
        body (StudentLearningState):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | UpdateTeacherStudentStateResponse200
     """


    return sync_detailed(
        course_id=course_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    course_id: str,
    *,
    client: AuthenticatedClient,
    body: StudentLearningState,

) -> Response[Any | UpdateTeacherStudentStateResponse200]:
    """
    Args:
        course_id (str):
        body (StudentLearningState):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | UpdateTeacherStudentStateResponse200]
     """


    kwargs = _get_kwargs(
        course_id=course_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    course_id: str,
    *,
    client: AuthenticatedClient,
    body: StudentLearningState,

) -> Any | UpdateTeacherStudentStateResponse200 | None:
    """
    Args:
        course_id (str):
        body (StudentLearningState):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | UpdateTeacherStudentStateResponse200
     """


    return (await asyncio_detailed(
        course_id=course_id,
client=client,
body=body,

    )).parsed
