import os
from PIL import Image, ImageDraw
from app.schemas.content import DocumentContent


def make_image(path, size=(1200, 700)):
    im = Image.new("RGB", size, (235, 240, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(30, 60, 140), width=8)
    d.line([40, 40, size[0] - 40, size[1] - 40], fill=(200, 50, 50), width=6)
    im.save(path)
    return path


def sample_content(lang="en", asset="img1") -> DocumentContent:
    base = lang.split("-")[0]
    AR = {"A Study of Template-Driven Documents": "دراسة للمستندات المبنية على القوالب",
          "Version 1": "الإصدار 1", "Author One": "المؤلف الأول", "Metropolitan University": "جامعة العاصمة",
          "Introduction": "مقدمة", "First paragraph.\nSecond line.": "الفقرة الأولى.\nالسطر الثاني.",
          "Motivation": "الدافع", "Motivation text.": "نص الدافع.", "Deep level": "مستوى عميق",
          "Results": "النتائج", "Experimental results": "النتائج التجريبية", "System architecture": "بنية النظام"}

    def t(e, o):
        if base == "en":
            return e
        if base == "ar":
            return AR.get(e, e)
        return o
    return DocumentContent.model_validate({
        "language": lang,
        "title": t("A Study of Template-Driven Documents", "টেমপ্লেট ভিত্তিক নথির একটি সমীক্ষা"),
        "subtitle": t("Version 1", "সংস্করণ ১"),
        "authors": [{"name": t("Author One", "লেখক এক"), "affiliation": t("Metropolitan University", "মেট্রোপলিটান বিশ্ববিদ্যালয়"), "email": "a@example.org"}],
        "abstract": ("هذه **خلاصة** تجريبية." if base == "ar" else
                     t("This paper tests **bold**, *italic*, H~2~O and x^2^.", "এটি একটি **সারসংক্ষেপ**।")),
        "keywords": ["docx", "templates"],
        "body": [
            {"type": "section", "id": "s1", "title": t("Introduction", "ভূমিকা"), "content": [
                {"type": "paragraph", "text": t("First paragraph.\nSecond line.", "প্রথম অনুচ্ছেদ।")},
                {"type": "section", "title": t("Motivation", "প্রেরণা"), "content": [
                    {"type": "paragraph", "text": t("Motivation text.", "প্রেরণার বর্ণনা।")},
                    {"type": "section", "title": t("Deep level", "গভীর স্তর"), "content": [
                        {"type": "paragraph", "text": "Deep text."}]},
                ]},
                {"type": "list", "ordered": False, "items": [
                    {"text": "Alpha", "children": [{"text": "Alpha-1"}, {"text": "Alpha-2"}]}, {"text": "Beta"}]},
                {"type": "list", "ordered": True, "items": [{"text": "One"}, {"text": "Two", "children": [{"text": "Two-a"}]}]},
                {"type": "list", "ordered": True, "items": [{"text": "Restart-one"}]},
            ]},
            {"type": "section", "title": t("Results", "ফলাফল"), "content": [
                {"type": "table", "caption": t("Experimental results", "পরীক্ষার ফলাফল"),
                 "data": [["Method", "Accuracy", "F1"], ["A", "91%", "0.90"], ["B", "94%", "0.93"]],
                 "source": "Author"},
                {"type": "table", "caption": "Second table", "data": [["x", "y"], ["1", "2"]]},
                {"type": "paragraph", "text": "Between."},
                {"type": "figure", "asset_id": asset, "caption": t("System architecture", "সিস্টেম কাঠামো"), "source": "Own"},
                {"type": "table", "caption": "Wide", "data": [[f"c{i}" for i in range(8)], [str(i) for i in range(8)]]},
            ]},
        ],
    })
