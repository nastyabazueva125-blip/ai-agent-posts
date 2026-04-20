"""
card_generator.py — генерация визуальных карточек-заголовков для постов.

Стиль: bazueva.design
  - Фон: бежевый/кремовый (#EAE7E1)
  - Заголовок: чёрный жирный гротеск (Inter/Noto Sans Display Black)
  - Акцент: синий (#2B2BFF) или лавандовый (#A89FFF)
  - Декор: синяя точка, тонкая линия под акцентным словом
  - Подпись: источник + хештег мелким шрифтом
  - Размер: 1080×1080 (квадрат для Telegram)
"""

import os
import textwrap
import random
from PIL import Image, ImageDraw, ImageFont

# ─── Пути к шрифтам ───────────────────────────────────────────────────────
FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

FONT_BLACK = os.path.join(FONTS_DIR, "InterVariable.ttf")  # Inter Variable (поддерживает wght)
FONT_DISPLAY_BLACK = "/usr/share/fonts/truetype/noto/NotoSansDisplay-Black.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/noto/NotoSansDisplay-Black.ttf"

# ─── Цветовая палитра ─────────────────────────────────────────────────────
BG_COLOR = (234, 231, 225)        # бежевый #EAE7E1
TEXT_BLACK = (20, 20, 20)         # почти чёрный
ACCENT_BLUE = (43, 43, 255)       # синий #2B2BFF
ACCENT_LAVENDER = (168, 159, 255) # лавандовый #A89FFF
ACCENT_GRAY = (160, 155, 148)     # серый для подписи

# ─── Размеры карточки ─────────────────────────────────────────────────────
CARD_W = 1080
CARD_H = 1080
PADDING = 80


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Загрузить шрифт с fallback."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Разбить текст на строки по максимальной ширине."""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines


def _split_accent(title: str) -> tuple[str, str, str]:
    """
    Разбить заголовок на три части: до акцента, акцент (середина), после акцента.
    Акцентируем среднее слово или самое длинное.
    """
    words = title.upper().split()
    if len(words) <= 2:
        return ("", title.upper(), "")

    # Берём примерно среднюю треть как акцент
    n = len(words)
    if n <= 4:
        mid = n // 2
        accent_words = [words[mid]]
        before = " ".join(words[:mid])
        after = " ".join(words[mid+1:])
    else:
        start = n // 3
        end = 2 * n // 3
        accent_words = words[start:end]
        before = " ".join(words[:start])
        after = " ".join(words[end:])

    return (before, " ".join(accent_words), after)


def generate_card(
    title: str,
    source: str = "",
    hashtag: str = "",
    output_path: str = "/tmp/card.jpg",
    accent_color: tuple = None,
) -> str:
    """
    Сгенерировать карточку-заголовок в стиле bazueva.design.

    Args:
        title: заголовок поста (на русском)
        source: источник (напр. "SaaStr")
        hashtag: хештег (напр. "#разборкейса")
        output_path: путь для сохранения
        accent_color: цвет акцента (по умолчанию случайно синий или лавандовый)

    Returns:
        путь к сохранённому файлу
    """
    if accent_color is None:
        accent_color = random.choice([ACCENT_BLUE, ACCENT_LAVENDER])

    img = Image.new("RGB", (CARD_W, CARD_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # ── Шрифты ──────────────────────────────────────────────────────────
    font_title_big = _load_font(FONT_DISPLAY_BLACK, 110)
    font_title_mid = _load_font(FONT_DISPLAY_BLACK, 90)
    font_title_sm  = _load_font(FONT_DISPLAY_BLACK, 72)
    font_sub       = _load_font(FONT_DISPLAY_BLACK, 32)

    max_text_w = CARD_W - PADDING * 2
    title_upper = title.upper()

    # Выбираем размер шрифта в зависимости от длины
    if len(title_upper) <= 30:
        font_main = font_title_big
    elif len(title_upper) <= 60:
        font_main = font_title_mid
    else:
        font_main = font_title_sm

    # ── Разбиваем заголовок на строки ────────────────────────────────────
    lines = _wrap_text(title_upper, font_main, max_text_w, draw)

    # Считаем общую высоту текста
    line_h = draw.textbbox((0, 0), "Ag", font=font_main)[3] + 12
    total_text_h = len(lines) * line_h

    # Вертикальное центрирование (чуть выше центра)
    start_y = (CARD_H - total_text_h) // 2 - 40

    # ── Рисуем строки ────────────────────────────────────────────────────
    # Определяем «акцентную» строку — среднюю
    accent_line_idx = len(lines) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        line_w = bbox[2] - bbox[0]
        x = PADDING  # выравнивание по левому краю (как на сайте)
        y = start_y + i * line_h

        if i == accent_line_idx:
            # Акцентная строка — цветная
            draw.text((x, y), line, font=font_main, fill=accent_color)
            # Подчёркивание под акцентной строкой
            underline_y = y + line_h - 8
            draw.rectangle(
                [x, underline_y, x + line_w, underline_y + 4],
                fill=accent_color
            )
        else:
            draw.text((x, y), line, font=font_main, fill=TEXT_BLACK)

    # ── Декоративная точка (справа, как на сайте) ────────────────────────
    dot_x = CARD_W - PADDING - 20
    dot_y = CARD_H // 2 - 20
    dot_r = 14
    draw.ellipse(
        [dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
        fill=ACCENT_BLUE
    )

    # ── Подпись внизу: источник + хештег ─────────────────────────────────
    bottom_y = CARD_H - PADDING - 20
    if source or hashtag:
        sub_parts = []
        if source:
            sub_parts.append(source.upper())
        if hashtag:
            sub_parts.append(hashtag.upper())
        sub_text = "  ·  ".join(sub_parts)
        draw.text((PADDING, bottom_y), sub_text, font=font_sub, fill=ACCENT_GRAY)

    # ── Логотип / подпись бренда (верхний левый угол) ─────────────────────
    logo_font = _load_font(FONT_DISPLAY_BLACK, 28)
    draw.text((PADDING, PADDING), "bazueva.design", font=logo_font, fill=ACCENT_GRAY)

    # ── Сохраняем ─────────────────────────────────────────────────────────
    img.save(output_path, "JPEG", quality=92)
    return output_path


# ─── Тест ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_titles = [
        ("13 способов получить больше просмотров на YouTube в 2026 году", "Buffer Blog", "#воронкиипродажи"),
        ("Клиенты всё чаще требуют короткие контракты", "SaaStr", "#разборкейса"),
        ("Как AI меняет правила игры в малом бизнесе", "Lenny's Newsletter", "#aiдлябизнеса"),
        ("Мышление победителя", "Seth Godin", "#мысливслух"),
    ]

    for i, (title, source, hashtag) in enumerate(test_titles):
        path = f"/tmp/test_card_{i+1}.jpg"
        result = generate_card(title, source, hashtag, path)
        print(f"✅ Карточка {i+1}: {result}")
