from enum import Enum

class StudentLearningStateStatus(str, Enum):
    COMPLETED = "completed"
    LEARNING = "learning"
    NEEDS_ATTENTION = "needs-attention"
    NOT_STARTED = "not-started"

    def __str__(self) -> str:
        return str(self.value)
