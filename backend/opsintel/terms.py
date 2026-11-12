import re

WORD_RE = re.compile(r"[\w][\w.-]{1,}", re.UNICODE)
NEVER_MATCH = re.compile(r"(?!x)x")
STOP_WORDS = {
    "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are",
    "around", "as", "at", "be", "because", "been", "before", "being", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "during", "each", "for", "from", "get", "got", "had", "has",
    "have", "how", "if", "in", "into", "is", "it", "its", "may", "might", "more", "most", "must",
    "of", "on", "or", "our", "out", "over", "please", "should", "so", "some", "such", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "under",
    "up", "use", "using", "was", "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "you", "your", "configure", "configured", "configures", "control", "controls",
    "setting", "settings",
}


def search_terms(question: str) -> list[str]:
    words = [word for word in WORD_RE.findall(question) if len(word) >= 3 and word.lower() not in STOP_WORDS]
    return list(dict.fromkeys(words))[:8]


def terms_pattern(terms: list[str]) -> re.Pattern:
    patterns = []
    for term in terms:
        parts = re.split(r"[_\-.]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", term)
        for value in (term, *parts):
            if not value:
                continue
            escaped = re.escape(value)
            left = r"(?<![A-Za-z0-9])|(?<=(?-i:[a-z0-9]))(?=(?-i:[A-Z]))"
            right = r"(?![A-Za-z0-9])|(?=(?-i:[A-Z]))"
            patterns.append(r"(?:" + left + ")" + escaped + r"(?:" + right + ")")
    return re.compile("|".join(dict.fromkeys(patterns)), re.IGNORECASE) if patterns else NEVER_MATCH


def substring_pattern(terms: list[str]) -> re.Pattern:
    values = [re.escape(part) for term in terms for part in re.split(r"[_\-.]+", term) if len(part) >= 3]
    return re.compile("|".join(values), re.IGNORECASE) if values else NEVER_MATCH
