FAMILIES = ("opus", "sonnet", "haiku", "other")

_COLORS = {"opus": "medium_purple1", "sonnet": "dark_orange", "haiku": "dodger_blue1", "other": "spring_green2"}


def family(model: str) -> str:
    for f in FAMILIES[:3]:
        if model.startswith(f):
            return f
    return "other"


def model_color(model: str) -> str:
    return _COLORS[family(model)]
