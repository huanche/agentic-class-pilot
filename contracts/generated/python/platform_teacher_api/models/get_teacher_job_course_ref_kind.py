from enum import Enum

class GetTeacherJobCourseRefKind(str, Enum):
    ARTIFACT = "artifact"
    GRAPH = "graph"

    def __str__(self) -> str:
        return str(self.value)
