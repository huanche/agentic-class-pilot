from enum import IntEnum

class PlatformLearningContextV1SchemaVersion(IntEnum):
    VALUE_1 = 1

    def __str__(self) -> str:
        return str(self.value)
