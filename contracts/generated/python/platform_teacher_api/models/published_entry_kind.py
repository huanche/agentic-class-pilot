from enum import Enum

class PublishedEntryKind(str, Enum):
    ARTIFACT = "artifact"
    LESSON_FILE = "lesson-file"
    MATERIAL = "material"

    def __str__(self) -> str:
        return str(self.value)
