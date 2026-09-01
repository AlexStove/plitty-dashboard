"""
Общие типы данных для проекта agentMUSIC.
"""

from dataclasses import dataclass, field


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class LyricsLine:
    text: str
    start: float
    end: float
    words: list[WordTiming] = field(default_factory=list)
