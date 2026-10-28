from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.enqueue_published_lesson_knowledge_at_student_body import EnqueuePublishedLessonKnowledgeAtStudentBody
from ...models.enqueue_published_lesson_knowledge_at_student_response_200 import EnqueuePublishedLessonKnowledgeAtStudentResponse200
from typing import cast



def _get_kwargs(
    *,
    body: EnqueuePublishedLessonKnowledgeAtStudentBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/internal/platform/published-lesson-knowledge",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200 | None:
    if response.status_code == 200:
        response_200 = EnqueuePublishedLessonKnowledgeAtStudentResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: EnqueuePublishedLessonKnowledgeAtStudentBody,

) -> Response[Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200]:
    """ Idempotently queue preparation for one verified published lesson revision

     The platform verifies publication and supplies the teacher-owned snapshot; the student service owns
    the durable job table.

    Args:
        body (EnqueuePublishedLessonKnowledgeAtStudentBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient,
    body: EnqueuePublishedLessonKnowledgeAtStudentBody,

) -> Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200 | None:
    """ Idempotently queue preparation for one verified published lesson revision

     The platform verifies publication and supplies the teacher-owned snapshot; the student service owns
    the durable job table.

    Args:
        body (EnqueuePublishedLessonKnowledgeAtStudentBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: EnqueuePublishedLessonKnowledgeAtStudentBody,

) -> Response[Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200]:
    """ Idempotently queue preparation for one verified published lesson revision

     The platform verifies publication and supplies the teacher-owned snapshot; the student service owns
    the durable job table.

    Args:
        body (EnqueuePublishedLessonKnowledgeAtStudentBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient,
    body: EnqueuePublishedLessonKnowledgeAtStudentBody,

) -> Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200 | None:
    """ Idempotently queue preparation for one verified published lesson revision

     The platform verifies publication and supplies the teacher-owned snapshot; the student service owns
    the durable job table.

    Args:
        body (EnqueuePublishedLessonKnowledgeAtStudentBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnqueuePublishedLessonKnowledgeAtStudentResponse200
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
