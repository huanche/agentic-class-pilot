from enum import Enum

class ReportStudentLearningProgressBodyEvent(str, Enum):
    ENDED = "ended"
    STARTED = "started"

    def __str__(self) -> str:
        return str(self.value)
