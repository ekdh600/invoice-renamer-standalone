import argparse
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader


logger = logging.getLogger("invoice_renamer")


@dataclass
class ExtractResult:
    company: str
    date: str  # YYYYMMDD or "Unknown"


def _clean_company_name(name: str) -> str:
    if not name:
        return "Unknown"
    s = name.strip()
    s = re.sub(r"^(상\s*호|업체명|회사명|법인명)\s*[:：]?\s*", "", s)
    s = re.sub(r"(성\s*명|이\s*름|담당자?|대표자?|귀\s*하|부\s*서|등록번호|주\s*소|업\s*태|종\s*목).*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 2:
        return "Unknown"
    s = re.sub(r'[\\/*?:"<>|]', "", s).strip()
    return s or "Unknown"


def _normalize_date_to_yyyymmdd(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "Unknown"
    if re.fullmatch(r"\d{8}", s):
        return s
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}{mo:02d}{d:02d}"
    m = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}{mo:02d}{d:02d}"
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", s)
    if m:
        return m.group(0)
    return "Unknown"


def _regex_extract_company_and_date(text: str) -> ExtractResult:
    boundary = r"(?=\s*(?:성\s*명|이\s*름|담당|대표|등록번호|주\s*소|업\s*태|종\s*목|귀\s*하|$))"

    # company candidates near labels
    candidates: list[str] = []
    for pat in [
        r"상\s*호\s*[:：]?\s*([가-힣()㈜주\s]{2,30}?)" + boundary,
        r"업체명\s*[:：]?\s*([가-힣()㈜주\s]{2,30}?)" + boundary,
        r"업\s*체(?!\s*명)\s*[:：]?\s*([가-힣()㈜주\s]{2,30}?)" + boundary,
    ]:
        for m in re.finditer(pat, text):
            c = _clean_company_name(m.group(1))
            if c != "Unknown":
                candidates.append(c)

    company = candidates[0] if candidates else "Unknown"

    # date candidates
    date = "Unknown"
    for m in re.finditer(r"(작성일|견적일|발행일|날짜|년월일)\s*[:：]?\s*([^\n]{0,20})", text):
        date = _normalize_date_to_yyyymmdd(m.group(2))
        if date != "Unknown":
            break
    if date == "Unknown":
        for pat in [r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", r"20\d{2}\d{2}\d{2}", r"20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"]:
            m = re.search(pat, text)
            if m:
                date = _normalize_date_to_yyyymmdd(m.group(0))
                if date != "Unknown":
                    break

    return ExtractResult(company=company, date=date)


def _pdf_to_text_pypdf(pdf_path: str) -> str:
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    return "\n".join([d.page_content for d in docs]).strip()


def _pdf_to_text_local_vlm_ocr(pdf_path: str, base_url: str, vision_model: str, ocr_dpi: int, max_pages: int) -> str:
    try:
        from pdf2image import convert_from_path
    except Exception as e:
        logger.warning(f"pdf2image not available: {e} (poppler 필요)")
        return ""

    images = convert_from_path(pdf_path, dpi=max(ocr_dpi, 220), first_page=1, last_page=max_pages)
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    max_side = 1536
    prompt = (
        "이 이미지는 견적서/문서야. 문서 안의 모든 텍스트를 그대로 추출해줘. "
        "손글씨(한글) 포함해서 읽을 수 있는 글자는 전부 적어줘. "
        "설명 없이 추출한 텍스트만 출력해."
    )

    out_pages: list[str] = []
    for image in images:
        try:
            from PIL import Image

            w, h = image.size
            if max(w, h) > max_side:
                ratio = max_side / max(w, h)
                nw, nh = int(w * ratio), int(h * ratio)
                resample = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                image = image.resize((nw, nh), resample)
        except Exception:
            pass

        import base64
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="invoice_page_")
        os.close(tmp_fd)
        try:
            image.save(tmp_path, "JPEG", quality=85)
            with open(tmp_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        payload = {
            "model": vision_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
        }
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        if not resp.ok:
            logger.warning(f"Local VLM OCR failed: {resp.status_code} {resp.text[:200]}")
            return ""
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            out_pages.append(content.strip())

    return "\n".join(out_pages).strip()


def _extract_via_local_llm(text: str, base_url: str, model: str) -> ExtractResult:
    endpoint = f"{base_url.rstrip('/')}/api/v1/chat"
    prompt = (
        "아래 견적서 텍스트에서 발행업체 상호명과 날짜를 추출해.\n"
        "- 반드시 JSON만 출력: {\"company_name\":\"...\",\"date\":\"YYYYMMDD 또는 Unknown\"}\n"
        "- 상호는 '상호/업체명' 라벨의 회사명 우선\n"
        "- 날짜는 YYYYMMDD 형식, 없으면 Unknown\n"
        f"[견적서 텍스트]\n{text[:6000]}\n[텍스트 끝]"
    )
    payload = {"model": model, "input": prompt}
    resp = requests.post(endpoint, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = ""
    if isinstance(data, dict):
        if isinstance(data.get("output"), str):
            content = data["output"]
        elif isinstance(data.get("text"), str):
            content = data["text"]
        elif isinstance(data.get("response"), str):
            content = data["response"]
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return ExtractResult(company="Unknown", date="Unknown")
    import json

    try:
        parsed = json.loads(m.group(0))
        company = _clean_company_name(str(parsed.get("company_name", "Unknown")))
        date = _normalize_date_to_yyyymmdd(str(parsed.get("date", "Unknown")))
        return ExtractResult(company=company, date=date)
    except Exception:
        return ExtractResult(company="Unknown", date="Unknown")


def extract_company_and_date_from_pdf(
    pdf_path: str,
    *,
    local_base_url: str,
    vision_model: str,
    text_model: str,
    prefer_clova: bool,
    ocr_dpi: int,
    max_pages: int,
) -> ExtractResult:
    # 1) OCR (local-first)
    text = _pdf_to_text_local_vlm_ocr(pdf_path, local_base_url, vision_model, ocr_dpi, max_pages)
    if not text:
        text = _pdf_to_text_pypdf(pdf_path)

    # 2) regex first
    r = _regex_extract_company_and_date(text)
    if r.company != "Unknown" and r.date != "Unknown":
        return r

    # 3) local llm fallback
    llm_r = _extract_via_local_llm(text, local_base_url, text_model)
    if llm_r.company != "Unknown":
        company = llm_r.company
    else:
        company = r.company
    date = llm_r.date if llm_r.date != "Unknown" else r.date
    return ExtractResult(company=company, date=date)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suf = path.stem, path.suffix
    for i in range(1, 9999):
        p = path.with_name(f"{stem}_{i}{suf}")
        if not p.exists():
            return p
    raise RuntimeError("failed to pick unique filename")


def rename_one(pdf: Path, out_dir: Path, cfg) -> Path:
    r = extract_company_and_date_from_pdf(
        str(pdf),
        local_base_url=cfg.local_base_url,
        vision_model=cfg.vision_model,
        text_model=cfg.text_model,
        prefer_clova=cfg.clova,
        ocr_dpi=cfg.ocr_dpi,
        max_pages=cfg.max_pages,
    )
    date = r.date if r.date != "Unknown" else "00000000"
    company = r.company if r.company != "Unknown" else "Unknown"
    target = out_dir / f"{company}_{date}.pdf"
    target = _unique_path(target)
    shutil.copy2(pdf, target)
    logger.info(f"{pdf.name} -> {target.name} (company={company}, date={date})")
    return target


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="견적서 파일명을 {상호}_{YYYYMMDD}.pdf 로 변경")
    parser.add_argument("--file", type=str, help="단일 PDF 파일 경로")
    parser.add_argument("--dir", type=str, help="PDF가 들어있는 디렉터리")
    parser.add_argument("--out", type=str, default="out", help="출력 디렉터리 (기본: out)")
    parser.add_argument("--clova", action="store_true", help="(옵션) CLOVA OCR 사용")
    parser.add_argument("--ocr-dpi", type=int, default=200, help="로컬 OCR 렌더링 DPI")
    parser.add_argument("--max-pages", type=int, default=1, help="처리할 페이지 수(기본: 1)")
    parser.add_argument("--local-base-url", type=str, default=os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"))
    parser.add_argument("--vision-model", type=str, default=os.getenv("LM_VISION_MODEL", "qwen/qwen2.5-vl-7b"))
    parser.add_argument("--text-model", type=str, default=os.getenv("LM_VISION_MODEL", "qwen/qwen2.5-vl-7b"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = argparse.Namespace(
        local_base_url=args.local_base_url,
        vision_model=args.vision_model,
        text_model=args.text_model,
        clova=args.clova,
        ocr_dpi=args.ocr_dpi,
        max_pages=max(1, min(args.max_pages, 10)),
    )

    if args.file:
        pdf = Path(args.file)
        rename_one(pdf, out_dir, cfg)
        return 0
    if args.dir:
        d = Path(args.dir)
        for pdf in sorted(d.glob("*.pdf")):
            rename_one(pdf, out_dir, cfg)
        return 0
    parser.error(" --file 또는 --dir 중 하나는 필수입니다.")
    return 2
