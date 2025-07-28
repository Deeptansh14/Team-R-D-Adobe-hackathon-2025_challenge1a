import json
import re
import unicodedata
from pathlib import Path
from collections import Counter
from typing import List, Dict
import fitz
import langid

CONFIG = {
    "HEADING_SIZE_FACTOR": 1.05,
    "HEADER_FOOTER_MARGIN": 0.00,
    "MAX_HEADING_LEVELS": 4,
    "BODY_SIZE_MIN_TEXT_LEN_LATIN": 5,
    "BODY_SIZE_MIN_TEXT_LEN_CJK": 5,
    "BODY_SIZE_MIN_TEXT_LEN_INDIC": 5,
    "HEADING_MAX_WORDS": 30,
    "TITLE_MAX_WORDS": 35,
}

def normalize_text_for_search(text: str) -> str:
    normalized = []
    for c in text:
        cat = unicodedata.category(c)
        if cat[0] in ("L", "N"):
            if "LATIN" in unicodedata.name(c, "").upper():
                normalized.append(c.lower())
            else:
                normalized.append(c)
    return "".join(normalized)

def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"
    lang, _ = langid.classify(text)
    return lang

def count_words_or_chars(text: str, lang_code: str) -> int:
    cjk_langs = {"zh", "ja", "ko", "th"}
    if lang_code in cjk_langs:
        return len(text.strip())
    else:
        return len(text.strip().split())

def min_body_text_len(lang_code: str) -> int:
    cjk_langs = {"zh", "ja", "ko", "th"}
    indic_langs = {"hi", "bn", "mr", "gu", "ta", "te", "kn", "ml", "or"}
    if lang_code in cjk_langs:
        return CONFIG["BODY_SIZE_MIN_TEXT_LEN_CJK"]
    elif lang_code in indic_langs:
        return CONFIG["BODY_SIZE_MIN_TEXT_LEN_INDIC"]
    else:
        return CONFIG["BODY_SIZE_MIN_TEXT_LEN_LATIN"]

def validate_and_fix_hierarchy(outline: List[Dict]) -> List[Dict]:
    if not outline:
        return outline

    fixed_outline = []
    level_context = []

    for i, heading in enumerate(outline):
        current_level = int(heading["level"][1])
    
        if i == 0:
            heading["level"] = "H1"
            level_context = [1]
            fixed_outline.append(heading)
            continue
    
        last_level = level_context[-1] if level_context else 1
    
        if current_level == last_level:
            fixed_outline.append(heading)
        elif current_level == last_level + 1:
            level_context.append(current_level)
            fixed_outline.append(heading)
        elif current_level > last_level + 1:
            new_level = min(last_level + 1, CONFIG["MAX_HEADING_LEVELS"])
            heading["level"] = f"H{new_level}"
            level_context.append(new_level)
            fixed_outline.append(heading)
        else:
            while level_context and level_context[-1] >= current_level:
                level_context.pop()
        
            if not level_context or current_level <= max(level_context) + 1:
                if current_level not in level_context:
                    level_context.append(current_level)
                fixed_outline.append(heading)
            else:
                parent_level = max(level_context) if level_context else 0
                new_level = min(parent_level + 1, CONFIG["MAX_HEADING_LEVELS"])
                heading["level"] = f"H{new_level}"
                level_context.append(new_level)
                fixed_outline.append(heading)

    return fixed_outline

def find_document_title(doc: fitz.Document) -> str:
    try:
        page = doc[0]
        blocks = page.get_text("dict", flags=4)["blocks"]
        lines_on_page = []
    
        for block in blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = " ".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                lines_on_page.append({
                    "text": text,
                    "size": spans[0]["size"],
                    "y0": line["bbox"][1],
                    "y1": line["bbox"][3],
                })
    
        if not lines_on_page:
            return ""
        
        def get_title_candidate(lines, ratio_thresh, line_spacing_factor, find_best_block):
            max_size = max(l.get("size", 0) for l in lines) if lines else 0
            if max_size == 0:
                return ""
        
            size_threshold = max_size * ratio_thresh
            candidates = [l for l in lines if l.get("size", 0) >= size_threshold]
            if not candidates:
                return ""
        
            candidates.sort(key=lambda x: x["y0"])
            blocks = []
            if candidates:
                current_block = [candidates[0]]
                for i in range(1, len(candidates)):
                    prev, curr = current_block[-1], candidates[i]
                    if curr["y0"] - prev["y1"] < prev["size"] * line_spacing_factor:
                        current_block.append(curr)
                    else:
                        blocks.append(current_block)
                        current_block = [curr]
                blocks.append(current_block)
        
            if not blocks:
                return ""
        
            chosen_block = (
                max(blocks, key=lambda b: (len(b), -b[0]["y0"]))
                if find_best_block else blocks[0]
            )
        
            title_text = " ".join(line["text"] for line in chosen_block).strip()
            if len(title_text.split()) > CONFIG["TITLE_MAX_WORDS"] or title_text.endswith("!"):
                return ""
            return title_text
        
        strict_title = get_title_candidate(lines_on_page, 0.90, 1.5, find_best_block=False)
        if len(strict_title) < 15:
            flexible_title = get_title_candidate(lines_on_page, 0.80, 1.8, find_best_block=True)
            if len(flexible_title) > len(strict_title):
                return flexible_title
        return strict_title
    except Exception as e:
        return ""

def get_font_style(line) -> Dict:
    if not line.get("spans"):
        return {"size": 0, "bold": False, "italic": False, "font": "", "color": ""}

    span = line["spans"][0]
    flags = span.get("flags", 0)
    font_name = span.get("font", "").lower()

    is_bold = (flags & 2**4) != 0 or any(b in font_name for b in ["bold", "bd", "blk", "black", "heavy"])
    is_italic = (flags & 2**6) != 0 or any(i in font_name for i in ["italic", "oblique", "slant"])

    return {
        "size": round(span.get("size", 0)),
        "bold": is_bold,
        "italic": is_italic,
        "font": span.get("font", "").lower(),
        "color": span.get("color", 0)
    }

def styles_match(style1: Dict, style2: Dict, size_tolerance: int = 1) -> bool:
    return (
        abs(style1["size"] - style2["size"]) <= size_tolerance and
        style1["bold"] == style2["bold"] and
        style1["italic"] == style2["italic"] and
        style1["font"] == style2["font"]
    )

def generate_outline_from_heuristics(doc: fitz.Document, title_text: str = "", lang_code: str = "en") -> List[Dict]:
    all_lines = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=0)["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = " ".join(s["text"] for s in spans).strip()
                if not text:
                    continue
            
                total_text_len = sum(len(s["text"]) for s in spans)
                if total_text_len == 0:
                    avg_size = 0
                else:
                    avg_size = sum(s["size"] * len(s["text"]) for s in spans) / total_text_len
            
                all_lines.append({
                    "text": text,
                    "size": avg_size,
                    "bbox": line["bbox"],
                    "page_num": page_num,
                    "spans": spans,
                })
                
    if not all_lines:
        return []

    normalized_title = normalize_text_for_search(title_text) if title_text else ""
    body_min_len = min_body_text_len(lang_code)
    body_text_candidates = [line for line in all_lines if len(line["text"]) > body_min_len]

    if not body_text_candidates:
        body_text_candidates = all_lines
    
    body_size_counts = Counter(round(ln["size"]) for ln in body_text_candidates)
    if not body_size_counts:
        return []
    
    body_size = body_size_counts.most_common(1)[0][0]
    heading_candidates = []
    page_height = doc[0].rect.height
    
    for i, line in enumerate(all_lines):
        item_count = count_words_or_chars(line["text"], lang_code)
        line_style = get_font_style(line)
    
        is_heading_style = (
            line["size"] >= CONFIG["HEADING_SIZE_FACTOR"] * body_size
            and 1 <= item_count <= CONFIG["HEADING_MAX_WORDS"]
            and CONFIG["HEADER_FOOTER_MARGIN"] * page_height < line["bbox"][1] < (1 - CONFIG["HEADER_FOOTER_MARGIN"]) * page_height
            and (not normalized_title or normalize_text_for_search(line["text"]) not in normalized_title)
        )
    
        is_bold_heading = (
            line_style["bold"]
            and body_size - 1 <= line_style["size"] <= body_size + 2
            and 2 <= item_count <= CONFIG["HEADING_MAX_WORDS"]
            and len(line["text"]) > 2
            and CONFIG["HEADER_FOOTER_MARGIN"] * page_height < line["bbox"][1] < (1 - CONFIG["HEADER_FOOTER_MARGIN"]) * page_height
            and (not normalized_title or normalize_text_for_search(line["text"]) not in normalized_title)
        )
    
        if not (is_heading_style or is_bold_heading):
            continue
            
        def is_valid_context(all_lines, i, body_size, body_min_len, lang_code):
            line = all_lines[i]
            current_page = line["page_num"]
            look_ahead_limit = min(i + 8, len(all_lines))
        
            if len(line["text"].strip()) < 3:
                return False
        
            text = line["text"].strip()
            if text.endswith(('.', ',', ';', ':', '!', '?', '"', "'", ')', ']', '}')) and not text.endswith('...'):
                return False
        
            if re.match(r'^\d+\.\s*$|^\w+\.\s*$|^[A-Z][a-z]*\s+of\s+\w+\s*[.:]?\s*$', text):
                return False
        
            copyright_patterns = [
                r'(?i)copyright\s*[©®™]?', r'(?i)copyright notice', r'(?i)©\s*\d{4}',
                r'(?i)version\s*\d+', r'(?i)v\.\s*\d+', r'(?i)ver\.\s*\d+',
                r'(?i)edition\s*\d*', r'(?i)published\s+(by|in)', r'(?i)isbn[\s:-]*\d',
                r'(?i)issn[\s:-]*\d', r'(?i)doi[\s:-]*\d', r'(?i)all\s+rights\s+reserved',
                r'(?i)proprietary\s+(and\s+)?confidential', r'(?i)patent\s+(no\.?|number)',
                r'(?i)trademark\s*[™®]?', r'(?i)license\s+(agreement|terms)',
                r'(?i)terms\s+of\s+use', r'(?i)legal\s+notice', r'(?i)disclaimer',
                r'(?i)privacy\s+policy', r'(?i)www\.\w+\.\w+', r'(?i)http[s]?://',
            ]
        
            for pattern in copyright_patterns:
                if re.search(pattern, text):
                    return False
        
            valid_body_lines_found = 0
            consecutive_valid_lines = 0
        
            for next_idx in range(i + 1, look_ahead_limit):
                next_line = all_lines[next_idx]
            
                if next_line["page_num"] != current_page:
                    break
                
                next_text = next_line.get("text", "").strip()
                if len(next_text) < 3:
                    continue
                
                next_item_count = count_words_or_chars(next_text, lang_code)
                next_size = round(next_line["size"])
            
                if next_size > line["size"] + 2:
                    break
                
                if (abs(next_size - body_size) <= 1 and 
                    next_item_count >= body_min_len and
                    len(next_text) >= 20):
                
                    valid_body_lines_found += 1
                    consecutive_valid_lines += 1
                
                    if consecutive_valid_lines >= 1 and next_item_count >= body_min_len * 1.5:
                        return True
                else:
                    consecutive_valid_lines = 0
                
                if next_idx - i > 4 and valid_body_lines_found == 0:
                    break
        
            return False
   
        if is_valid_context(all_lines, i, body_size, body_min_len, lang_code):
            heading_candidates.append(line)
            
    if not heading_candidates:
        return []

    heading_styles = []
    for heading in heading_candidates:
        style = get_font_style(heading)
        if style["size"] > 0:
            heading_styles.append(style)
            
    if not heading_styles:
        return []

    heading_texts = set(line["text"] for line in heading_candidates)
    additional_headings = []

    for line in all_lines:
        if line["text"] in heading_texts:
            continue
        line_style = get_font_style(line)
        if line_style["size"] == 0:
            continue
            
        style_matched = False
        for heading_style in heading_styles:
            if styles_match(line_style, heading_style, size_tolerance=1):
                style_matched = True
                break
                
        if not style_matched:
            continue
            
        item_count = count_words_or_chars(line["text"], lang_code)
        is_reasonable_heading = (
            2 <= item_count <= CONFIG["HEADING_MAX_WORDS"]
            and len(line["text"]) > 2
            and CONFIG["HEADER_FOOTER_MARGIN"] * page_height < line["bbox"][1] < (1 - CONFIG["HEADER_FOOTER_MARGIN"]) * page_height
            and (not normalized_title or normalize_text_for_search(line["text"]) not in normalized_title)
        )
        
        if is_reasonable_heading:
            additional_headings.append(line)
            heading_texts.add(line["text"])

    all_headings = heading_candidates + additional_headings
    if not all_headings:
        return []

    unique_sizes = set(round(h["size"]) for h in all_headings)
    ranked_sizes = sorted(list(unique_sizes), reverse=True)
    size_to_level = {size: f"H{i+1}" for i, size in enumerate(ranked_sizes[: CONFIG["MAX_HEADING_LEVELS"]])}
    
    initial_headings = []
    for h in all_headings:
        size = round(h["size"])
        level = size_to_level.get(size)
        if level:
            initial_headings.append({
                "level": level, "text": h["text"], "page": h["page_num"], "bbox": h["bbox"]
            })
            
    if not initial_headings:
        return []

    initial_headings.sort(key=lambda h: (h["page"], h["bbox"][1]))
    merged_headings = []
    merged_headings.append(initial_headings[0])

    for i in range(1, len(initial_headings)):
        prev, curr = merged_headings[-1], initial_headings[i]
        if (curr["page"] == prev["page"]
            and curr["level"] == prev["level"]
            and -2 <= (curr["bbox"][1] - prev["bbox"][3]) < (prev["bbox"][3] - prev["bbox"][1]) * 0.75):
            prev["text"] = prev["text"].rstrip() + " " + curr["text"]
        else:
            merged_headings.append(curr)
            
    return [{"level": h["level"], "text": h["text"], "page": h["page"]} for h in merged_headings]

def extract_headings(pdf_path: Path) -> (str, List[Dict]):
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return "", []

    sample_text = "".join(doc[i].get_text() for i in range(min(3, len(doc))))
    lang_code = detect_language(sample_text)

    title = find_document_title(doc)
    candidate_outline = []

    toc = doc.get_toc(simple=True)
    if toc:
        levels = [item[0] for item in toc]
        min_level = min(levels) if levels else 1
        candidate_outline = [
            {"level": f"H{item[0] - min_level + 1}", "text": item[1].strip(), "page": item[2] - 1}
            for item in toc if item[2] > 0
        ]
    else:
        candidate_outline = generate_outline_from_heuristics(doc, title_text=title, lang_code=lang_code)

    page_texts_normalized = {i: normalize_text_for_search(page.get_text()) for i, page in enumerate(doc)}
    normalized_title = normalize_text_for_search(title) if title else ""
    
    final_outline = []
    for heading in candidate_outline:
        page_num = heading["page"]
        heading_text_normalized = normalize_text_for_search(heading["text"])
        is_valid = page_num in page_texts_normalized and heading_text_normalized in page_texts_normalized[page_num]
        is_part_of_title = title and heading_text_normalized in normalized_title
        if is_valid and not is_part_of_title:
            final_outline.append(heading)

    final_outline = validate_and_fix_hierarchy(final_outline)
    doc.close()
    return title, final_outline

def process_pdfs():
    input_dir = Path("./input")
    output_dir = Path("./output")
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    
    pdfs = list(input_dir.glob("*.pdf"))
    if not pdfs:
        return

    for pdf in pdfs:
        title, outline = extract_headings(pdf)
    
        hierarchy_str = " -> ".join([f"{h['level']}" for h in outline])
    
        output = {"title": title, "outline": outline}
    
        out_path = output_dir / f"{pdf.stem}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    process_pdfs()
