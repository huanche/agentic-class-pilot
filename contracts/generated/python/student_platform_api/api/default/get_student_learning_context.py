from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_student_learning_context_body import GetStudentLearningContextBody
from ...models.platform_learning_context_v1 import PlatformLearningContextV1
from typing import cast



def _get_kwargs(
    *,
    body: GetStudentLearningContextBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/internal/student/learning-context",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | PlatformLearningContextV1 | None:
    if response.status_code == 200:
        response_200 = PlatformLearningContextV1.from_dict(response.json())



        return response_200

    if response.status_code == 401:
        response_401 = cast(Any, None)
        return response_401

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 409:
        response_409 = cast(Any, None)
        return response_409

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | PlatformLearningContextV1]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: GetStudentLearningContextBody,

) -> Response[Any | PlatformLearningContextV1]:
    """ 课堂学习上下文（版本化数据面，schemaVersion = 1）

     学生端启动课堂会话时调用。返回教师端已发布内容的完整投影： 知识包、课堂场景、课时结构与引用素材。客户端必须校验 schemaVersion；只加字段不改语义，破坏性变更升版本。

    Args:
        body (GetStudentLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | PlatformLearningContextV1]
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
    body: GetStudentLearningContextBody,

) -> Any | PlatformLearningContextV1 | None:
    """ 课堂学习上下文（版本化数据面，schemaVersion = 1）

     学生端启动课堂会话时调用。返回教师端已发布内容的完整投影： 知识包、课堂场景、课时结构与引用素材。客户端必须校验 schemaVersion；只加字段不改语义，破坏性变更升版本。

    Args:
        body (GetStudentLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | PlatformLearningContextV1
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: GetStudentLearningContextBody,

) -> Response[Any | PlatformLearningContextV1]:
    """ 课堂学习上下文（版本化数据面，schemaVersion = 1）

     学生端启动课堂会话时调用。返回教师端已发布内容的完整投影： 知识包、课堂场景、课时结构与引用素材。客户端必须校验 schemaVersion；只加字段不改语义，破坏性变更升版本。

    Args:
        body (GetStudentLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | PlatformLearningContextV1]
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
    body: GetStudentLearningContextBody,

) -> Any | PlatformLearningContextV1 | None:
    """ 课堂学习上下文（版本化数据面，schemaVersion = 1）

     学生端启动课堂会话时调用。返回教师端已发布内容的完整投影： 知识包、课堂场景、课时结构与引用素材。客户端必须校验 schemaVersion；只加字段不改语义，破坏性变更升版本。

    Args:
        body (GetStudentLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | PlatformLearningContextV1
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
