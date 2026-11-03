from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_student_classroom_view_body import GetStudentClassroomViewBody
from ...models.get_student_classroom_view_response_200 import GetStudentClassroomViewResponse200
from typing import cast



def _get_kwargs(
    *,
    body: GetStudentClassroomViewBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/internal/student/classroom-view",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetStudentClassroomViewResponse200 | None:
    if response.status_code == 200:
        response_200 = GetStudentClassroomViewResponse200.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetStudentClassroomViewResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: GetStudentClassroomViewBody,

) -> Response[Any | GetStudentClassroomViewResponse200]:
    """ 旧会话回放所需的课堂场景投影（替代学生端直查教师课堂表）

     按课堂 ID 返回可见文字与旁白投影，供旧会话恢复课堂画面使用。 平台负责从教师服务或自身历史读取；课堂不存在时返回空场景， 与旧直查行为一致。服务密钥认证；不做按学生的二次鉴权， 课堂 ID
    来自学生端已签名的会话。

    Args:
        body (GetStudentClassroomViewBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetStudentClassroomViewResponse200]
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
    body: GetStudentClassroomViewBody,

) -> Any | GetStudentClassroomViewResponse200 | None:
    """ 旧会话回放所需的课堂场景投影（替代学生端直查教师课堂表）

     按课堂 ID 返回可见文字与旁白投影，供旧会话恢复课堂画面使用。 平台负责从教师服务或自身历史读取；课堂不存在时返回空场景， 与旧直查行为一致。服务密钥认证；不做按学生的二次鉴权， 课堂 ID
    来自学生端已签名的会话。

    Args:
        body (GetStudentClassroomViewBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetStudentClassroomViewResponse200
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: GetStudentClassroomViewBody,

) -> Response[Any | GetStudentClassroomViewResponse200]:
    """ 旧会话回放所需的课堂场景投影（替代学生端直查教师课堂表）

     按课堂 ID 返回可见文字与旁白投影，供旧会话恢复课堂画面使用。 平台负责从教师服务或自身历史读取；课堂不存在时返回空场景， 与旧直查行为一致。服务密钥认证；不做按学生的二次鉴权， 课堂 ID
    来自学生端已签名的会话。

    Args:
        body (GetStudentClassroomViewBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetStudentClassroomViewResponse200]
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
    body: GetStudentClassroomViewBody,

) -> Any | GetStudentClassroomViewResponse200 | None:
    """ 旧会话回放所需的课堂场景投影（替代学生端直查教师课堂表）

     按课堂 ID 返回可见文字与旁白投影，供旧会话恢复课堂画面使用。 平台负责从教师服务或自身历史读取；课堂不存在时返回空场景， 与旧直查行为一致。服务密钥认证；不做按学生的二次鉴权， 课堂 ID
    来自学生端已签名的会话。

    Args:
        body (GetStudentClassroomViewBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetStudentClassroomViewResponse200
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
