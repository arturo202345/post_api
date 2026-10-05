from django import template

register = template.Library()


@register.filter
def dinero(v):
    """80 -> $80.00 (mismo formato que la app)."""
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "$0.00"


@register.filter
def pct(v):
    """Porcentaje entero 0-100 como texto (para usar en style="width: ..%" sin comas decimales)."""
    try:
        return str(max(0, min(100, int(round(float(v))))))
    except (TypeError, ValueError):
        return "0"


@register.filter
def etiqueta(v):
    """EN_CURSO -> En curso"""
    return str(v).replace("_", " ").capitalize()
