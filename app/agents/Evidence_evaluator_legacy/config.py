from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceEvaluatorConfig:
    temperature: float = 0.0
    max_output_tokens: int = 1500

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")

        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer.")
