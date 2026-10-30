from enum import Enum

class GetTeacherPublishedLessonResponse200ReasonType1(str, Enum):
    CLASSROOM_MISSING = "classroom-missing"
    NOT_A_LESSON_VIDEO = "not-a-lesson-video"
    NOT_PUBLISHED = "not-published"

    def __str__(self) -> str:
        return str(self.value)
