from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.report_student_learning_progress_body import ReportStudentLearningProgressBody
from ...models.report_student_learning_progress_response_200 import ReportStudentLearningProgressResponse200
from typing import cast



def _get_kwargs(
    *,
    body: ReportStudentLearningProgressBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/internal/student/learning-progress",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | ReportStudentLearningProgressResponse200 | None:
    if response.status_code == 200:
        response_200 = ReportStudentLearningProgressResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 400:
        response_400 = cast(Any, None)
        return response_400

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | ReportStudentLearningProgressResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ReportStudentLearningProgressBody,

) -> Response[Any | ReportStudentLearningProgressResponse200]:
    r""" 课堂进度事件上报（平台据此计算真实进度并推送教师端）

     event 仅接受 \"started\" / \"ended\"。

    Args:
        body (ReportStudentLearningProgressBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ReportStudentLearningProgressResponse200]
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
    body: ReportStudentLearningProgressBody,

) -> Any | ReportStudentLearningProgressResponse200 | None:
    r""" 课堂进度事件上报（平台据此计算真实进度并推送教师端）

     event 仅接受 \"started\" / \"ended\"。

    Args:
        body (ReportStudentLearningProgressBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ReportStudentLearningProgressResponse200
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ReportStudentLearningProgressBody,

) -> Response[Any | ReportStudentLearningProgressResponse200]:
    r""" 课堂进度事件上报（平台据此计算真实进度并推送教师端）

     event 仅接受 \"started\" / \"ended\"。

    Args:
        body (ReportStudentLearningProgressBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ReportStudentLearningProgressResponse200]
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
    body: ReportStudentLearningProgressBody,

) -> Any | ReportStudentLearningProgressResponse200 | None:
    r""" 课堂进度事件上报（平台据此计算真实进度并推送教师端）

     event 仅接受 \"started\" / \"ended\"。

    Args:
        body (ReportStudentLearningProgressBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ReportStudentLearningProgressResponse200
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
