from enum import Enum

class AuthorizeStudentRequestResponse200Source(str, Enum):
    LAUNCH_TOKEN = "launch_token"
    SESSION = "session"

    def __str__(self) -> str:
        return str(self.value)
