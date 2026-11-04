from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextCompressionConfig:
    """Controls when and how retrieved context is compressed."""

    token_threshold: int = 12000
    chars_per_token: int = 4
    temperature: float = 0.0
    max_output_tokens: int = 6000

    def __post_init__(self) -> None:
        if isinstance(self.token_threshold, bool) or not isinstance(self.token_threshold, int) or self.token_threshold <= 0:
            raise ValueError("token_threshold must be a positive integer.")
        if isinstance(self.chars_per_token, bool) or not isinstance(self.chars_per_token, int) or self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be a positive integer.")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")
        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int) or self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer.")
