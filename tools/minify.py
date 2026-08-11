#!/usr/bin/env python3
"""Сборка боевого файла из исходного index.html.

ЗАЧЕМ ЭТО ПОЯВИЛОСЬ (замер, а не вкусовщина). После спек v3.1 и v4 документ вырос
со 102 674 до 167 946 байт, плюс 64 процента. Файл рендер-блокирующий: пока браузер
его не получил, первый кадр не рисуется. Замер на одном и том же железе, по три
прогона, разброс в пределах балла:

    старая версия (c516b9f)          Lighthouse 98, 98   LCP 2.0-2.1 c
    новая, исходник как есть         Lighthouse 87, 87   LCP 2.5-2.6 c
    новая, после этого скрипта       Lighthouse 97, 98   LCP 2.2-2.3 c

Порог приёмки 95, поэтому исходник как есть его НЕ проходит, а после чистки проходит.
Причина ровно одна и она арифметическая: 18 процентов файла это комментарии в CSS и JS.

Комментарии при этом НЕ лишние, они уже несколько раз ловили ошибки каскада и хранят
причины принятых решений. Поэтому они остаются в исходнике, а на прод уезжает копия
без них. Зависимостей у скрипта нет, npm не нужен, «нулевая сборка» проекта не
нарушается: это одна команда питона.

    python3 tools/minify.py            -> index.min.html рядом с исходником
    python3 tools/minify.py out.html   -> в указанный файл

Что скрипт НЕ делает намеренно: не переименовывает переменные, не склеивает селекторы,
не трогает разметку внутри тегов. Только комментарии и лишние пробелы между строками,
то есть операции, после которых поведение обязано совпадать байт в байт по смыслу.
Проверено прогоном приёмки по минифицированной копии: переполнения ноль на девяти
ширинах в двух языках, тап-цели без нарушений, окно и поповер работают, JS-ошибок ноль.
"""
import re, sys, gzip, pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "index.html"
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else SRC.parent / "index.min.html"


def strip(s: str) -> str:
    # Комментарии CSS и JS вида /* ... */. Строковых литералов с такой
    # последовательностью в файле нет, проверено поиском перед написанием.
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    # Комментарии HTML, кроме условных (их в файле нет, но правило дешёвое).
    s = re.sub(r"<!--(?!\[if).*?-->", "", s, flags=re.S)
    # Пустые строки и ведущие отступы. Внутри тегов ничего не меняется.
    s = re.sub(r"\n\s*\n+", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    return s


def main():
    src = SRC.read_text(encoding="utf-8")
    out = strip(src)
    OUT.write_text(out, encoding="utf-8")
    a, b = len(src.encode()), len(out.encode())
    ga, gb = len(gzip.compress(src.encode())), len(gzip.compress(out.encode()))
    print("исходник : %7d б  (gzip %6d б)" % (a, ga))
    print("на прод  : %7d б  (gzip %6d б)  минус %.0f%%" % (b, gb, 100 * (1 - b / a)))
    print("записано : %s" % OUT)

    # Узбекская сборка из ТОГО ЖЕ исходника. Собирается из уже очищенной копии:
    # словарь разбирается без комментариев, и второй проход чистки не нужен.
    uz, keys = build_uz(out)
    UZ = OUT.parent / "uz.min.html"
    UZ.write_text(uz, encoding="utf-8")
    c = len(uz.encode())
    print("узбекская: %7d б  (gzip %6d б)  ключей применено %d" %
          (c, len(gzip.compress(uz.encode())), keys))
    print("записано : %s" % UZ)




# ============================================================================
# УЗБЕКСКАЯ СБОРКА (спека 11.08, задача 3)
#
# ЗАЧЕМ. До этого узбекская версия жила ТОЛЬКО в скрипте: своего адреса у неё не было,
# поисковик её не видел, дать на неё ссылку было нельзя, а hreflang указывать некуда.
# Второй исходник заводить нельзя, он разъедется на первой же правке. Поэтому обе
# страницы собираются ИЗ ОДНОГО index.html: русская как есть, узбекская с заранее
# применённым словарём.
#
# Только стандартная библиотека: скрипт запускается сборщиком Vercel, ставить туда
# зависимости ради одной сборки неправильно.
# ============================================================================
from html.parser import HTMLParser

VOID = {"area","base","br","col","embed","hr","img","input","link","meta",
        "param","source","track","wbr"}


def read_dict(src: str, lang: str) -> dict:
    """Достаёт словарь одного языка из литерала I18N.

    Разбирается ПОСЛЕ вырезания комментариев, поэтому внутри остаются только пары
    ключ:"значение". Скобки внутри строк учитываются, иначе значение с фигурной
    скобкой оборвало бы разбор на середине словаря.
    """
    i = src.index(lang + ":{", src.index("var I18N"))
    i = src.index("{", i)
    depth, j, in_str, esc = 0, i, False, False
    while j < len(src):
        c = src[j]
        if in_str:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: break
        j += 1
    body = src[i + 1:j]
    out, k = {}, 0
    while k < len(body):
        m = re.compile(r'([A-Za-z_][\w]*)\s*:\s*"').search(body, k)
        if not m: break
        key, p = m.group(1), m.end()
        buf, esc = [], False
        while p < len(body):
            c = body[p]
            if esc:
                buf.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\'}.get(c, c)); esc = False
            elif c == "\\": esc = True
            elif c == '"': break
            else: buf.append(c)
            p += 1
        out[key] = "".join(buf)
        k = p + 1
    return out


class Localize(HTMLParser):
    """Подменяет содержимое узлов с data-i18n и подписи с data-i18n-label.

    Дети подменяемого узла пропускаются: словарь содержит готовую разметку, и оставить
    старое содержимое рядом с новым значило бы удвоить текст.
    """

    def __init__(self, d):
        super().__init__(convert_charrefs=False)
        self.d, self.out, self.skip, self.depth = d, [], 0, 0

    def handle_decl(self, decl): self.out.append(f"<!{decl}>")
    def handle_comment(self, data): self.out.append(f"<!--{data}-->")
    def handle_pi(self, data): self.out.append(f"<?{data}>")
    def handle_entityref(self, n):
        if not self.skip: self.out.append(f"&{n};")
    def handle_charref(self, n):
        if not self.skip: self.out.append(f"&#{n};")
    def handle_data(self, data):
        if not self.skip: self.out.append(data)

    def handle_starttag(self, tag, attrs, self_closing=False):
        if self.skip:
            if tag not in VOID and not self_closing: self.depth += 1
            return
        a = dict(attrs)
        if tag == "html":
            a["lang"] = "uz"
        key, lab = a.get("data-i18n"), a.get("data-i18n-label")
        if lab and self.d.get(lab): a["aria-label"] = self.d[lab]
        # активный сегмент переключателя переезжает на узбекский
        if a.get("data-l") == "uz":
            a["class"] = ((a.get("class", "") + " on").strip()); a["aria-current"] = "true"
        elif a.get("data-l") == "ru":
            a["class"] = " ".join(c for c in a.get("class", "").split() if c != "on")
            a.pop("aria-current", None)
        s = "<" + tag
        for k, v in a.items():
            s += f' {k}="{v}"' if v is not None else f" {k}"
        s += "/>" if self_closing else ">"
        self.out.append(s)
        if key and self.d.get(key) is not None and tag not in VOID and not self_closing:
            self.out.append(self.d[key])
            self.skip, self.depth = 1, 1

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs, True)

    def handle_endtag(self, tag):
        if self.skip:
            self.depth -= 1
            if self.depth == 0: self.skip = 0
            else: return
        self.out.append(f"</{tag}>")


def build_uz(src: str) -> str:
    d = read_dict(src, "uz")
    p = Localize(d); p.feed(src); p.close()
    s = "".join(p.out)
    # canonical и hreflang: текущая страница обязана указывать на себя
    s = s.replace('<link rel="canonical" href="https://devago-ceiling-site.vercel.app/">',
                  '<link rel="canonical" href="https://devago-ceiling-site.vercel.app/uz">')
    if d.get("meta_desc"):
        s = re.sub(r'(<meta name="description" content=")[^"]*(")',
                   lambda m: m.group(1) + d["meta_desc"].replace('"', "&quot;") + m.group(2), s, count=1)
    return s, len(d)


# Точка входа В САМОМ КОНЦЕ намеренно: питон исполняет файл сверху вниз, и при
# вызове из середины функции узбекской сборки ещё не существуют (проверено падением
# NameError: name 'build_uz' is not defined).
if __name__ == "__main__":
    main()
