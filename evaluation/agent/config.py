from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionGenerationConfig:
    max_questions: int = 3
    temperature: float = 0.3
    max_output_tokens: int = 1800

    def __post_init__(self) -> None:
        if not 1 <= self.max_questions <= 3:
            raise ValueError("max_questions must be between 1 and 3.")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be greater than zero.")
